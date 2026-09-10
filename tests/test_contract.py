from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from rofi_ssh_plus.cli import MAX_STDERR_BYTES, MAX_STDOUT_BYTES, main
from rofi_ssh_plus.mesh import (
    MAX_ERROR_MESSAGE_CODEPOINTS,
    MAX_HOSTS,
    MAX_SOURCE_CODEPOINTS,
    MAX_STRING_CODEPOINTS,
    MAX_TIMESTAMP_MS,
    current_time_ms,
)


BUNDLE = Path(__file__).parents[1] / "contracts" / "host-mesh-v1"
SCHEMAS = BUNDLE / "schemas"
FIXTURES = BUNDLE / "fixtures"
SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


class SchemaValidationError(AssertionError):
    pass


class LocalSchemaValidator:
    """Small offline validator for the Draft 2020-12 subset used by P9.

    This is intentionally test-only.  The executable never imports or reads
    contract artifacts.  Supporting refs, required fields, primitive types,
    bounds, patterns, and the composition keywords used by these schemas
    gives the producer gate an independent structural check without adding a
    runtime or network dependency.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.documents = {
            path.resolve(): json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(root.glob("*.schema.json"))
        }

    def validate(self, instance: object, schema_path: str | Path) -> None:
        path = (self.root / schema_path).resolve()
        self._validate(instance, self.documents[path], path, "$")

    def _resolve(self, base: Path, reference: str) -> tuple[Path, object]:
        if reference.startswith("#"):
            path = base
            fragment = reference[1:]
        else:
            document, separator, fragment = reference.partition("#")
            if not separator or document.startswith(("http://", "https://")):
                raise SchemaValidationError(f"non-local schema ref: {reference}")
            path = (base.parent / document).resolve()
        if path not in self.documents:
            raise SchemaValidationError(f"missing schema ref: {reference}")
        value: object = self.documents[path]
        if fragment:
            if not fragment.startswith("/"):
                raise SchemaValidationError(f"unsupported schema fragment: {reference}")
            for token in fragment[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                if not isinstance(value, dict) or token not in value:
                    raise SchemaValidationError(f"missing schema pointer: {reference}")
                value = value[token]
        return path, value

    @staticmethod
    def _type_matches(instance: object, expected: str) -> bool:
        if expected == "object":
            return isinstance(instance, dict)
        if expected == "array":
            return isinstance(instance, list)
        if expected == "string":
            return isinstance(instance, str)
        if expected == "boolean":
            return isinstance(instance, bool)
        if expected == "integer":
            return isinstance(instance, int) and not isinstance(instance, bool)
        if expected == "number":
            return isinstance(instance, (int, float)) and not isinstance(instance, bool)
        if expected == "null":
            return instance is None
        return False

    @staticmethod
    def _json_equal(left: object, right: object) -> bool:
        """Compare JSON values without Python's bool/int aliasing."""

        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        return left == right

    def _validate(
        self, instance: object, schema: object, base: Path, location: str
    ) -> None:
        if not isinstance(schema, dict):
            raise SchemaValidationError(f"{location}: schema is not an object")
        if "$ref" in schema:
            ref_base, target = self._resolve(base, schema["$ref"])
            self._validate(instance, target, ref_base, location)
        for branch in schema.get("allOf", []):
            self._validate(instance, branch, base, location)
        for keyword, expected_count in (("anyOf", 1), ("oneOf", 1)):
            if keyword not in schema:
                continue
            successes = 0
            for branch in schema[keyword]:
                try:
                    self._validate(instance, branch, base, location)
                except SchemaValidationError:
                    continue
                successes += 1
            if (keyword == "anyOf" and successes < expected_count) or (
                keyword == "oneOf" and successes != expected_count
            ):
                raise SchemaValidationError(f"{location}: {keyword} failed")
        if "not" in schema:
            try:
                self._validate(instance, schema["not"], base, location)
            except SchemaValidationError:
                pass
            else:
                raise SchemaValidationError(f"{location}: not failed")
        if "const" in schema and not self._json_equal(instance, schema["const"]):
            raise SchemaValidationError(f"{location}: expected {schema['const']!r}")
        if "enum" in schema and not any(
            self._json_equal(instance, value) for value in schema["enum"]
        ):
            raise SchemaValidationError(f"{location}: value is not in enum")
        if "type" in schema:
            expected_types = schema["type"]
            if isinstance(expected_types, str):
                expected_types = [expected_types]
            if not any(self._type_matches(instance, value) for value in expected_types):
                raise SchemaValidationError(f"{location}: type mismatch")
        if isinstance(instance, str):
            if len(instance) < schema.get("minLength", 0):
                raise SchemaValidationError(f"{location}: string is too short")
            if len(instance) > schema.get("maxLength", 2**63 - 1):
                raise SchemaValidationError(f"{location}: string is too long")
            if "pattern" in schema and re.search(schema["pattern"], instance) is None:
                raise SchemaValidationError(f"{location}: pattern mismatch")
        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if "minimum" in schema and instance < schema["minimum"]:
                raise SchemaValidationError(f"{location}: below minimum")
            if "maximum" in schema and instance > schema["maximum"]:
                raise SchemaValidationError(f"{location}: above maximum")
        if isinstance(instance, list):
            if len(instance) < schema.get("minItems", 0):
                raise SchemaValidationError(f"{location}: too few items")
            if len(instance) > schema.get("maxItems", 2**63 - 1):
                raise SchemaValidationError(f"{location}: too many items")
            if "items" in schema:
                for index, item in enumerate(instance):
                    self._validate(item, schema["items"], base, f"{location}[{index}]")
        if isinstance(instance, dict):
            for name in schema.get("required", []):
                if name not in instance:
                    raise SchemaValidationError(f"{location}: missing {name}")
            for name, child in schema.get("properties", {}).items():
                if name in instance:
                    self._validate(instance[name], child, base, f"{location}.{name}")
            if schema.get("additionalProperties") is False:
                unknown = set(instance) - set(schema.get("properties", {}))
                if unknown:
                    raise SchemaValidationError(f"{location}: unknown {min(unknown)}")


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def decode_wire(raw: bytes) -> object:
    """Validate the P9 raw-wire envelope before JSON Schema validation."""

    if len(raw) > MAX_STDOUT_BYTES:
        raise ValueError("stdout overflow")
    if b"\x00" in raw:
        raise ValueError("embedded NUL")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("byte-order mark")
    if not raw.endswith(b"\n") or raw[:-1].endswith((b" ", b"\t", b"\r", b"\n")):
        raise ValueError("missing or extra final whitespace")
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid UTF-8") from exc
    try:
        decoder = json.JSONDecoder(
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_constant,
        )
        value, end = decoder.raw_decode(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON document") from exc
    if end != len(text):
        raise ValueError("trailing byte or extra document")
    return value


def _assert_list_semantics(value: object) -> None:
    if not isinstance(value, dict):
        raise AssertionError("list response is not an object")
    hosts = value["hosts"]
    if len(hosts) > MAX_HOSTS or not hosts:
        raise AssertionError("invalid host count")
    local_id = value["localHostId"]
    if hosts[0]["local"] is not True or hosts[0]["id"] != local_id:
        raise AssertionError("local host is not the first descriptor")
    if sum(item["local"] is True for item in hosts) != 1:
        raise AssertionError("list must contain exactly one local descriptor")
    ids: set[str] = set()
    identities: dict[str, str] = {}
    for host in hosts:
        key = host["id"].casefold()
        if key in ids:
            raise AssertionError("duplicate host ID")
        ids.add(key)
        previous = identities.setdefault(key, key)
        if previous != key:
            raise AssertionError("host ID collides with another host identity")
        if host["local"] and host["routes"]:
            raise AssertionError("local host has a route")
        if not host["local"] and not host["routes"]:
            raise AssertionError("remote host has no route")
        route_indices = [route["configuredIndex"] for route in host["routes"]]
        if sorted(route_indices) != list(range(len(route_indices))):
            raise AssertionError("duplicate route configured index")
        for alias in host["aliases"]:
            identity = alias.casefold()
            previous = identities.setdefault(identity, key)
            if previous != key:
                raise AssertionError("alias maps to multiple hosts")
        for route in host["routes"]:
            identity = route["destination"].casefold()
            previous = identities.setdefault(identity, key)
            if previous != key:
                raise AssertionError("route maps to multiple hosts")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value["meshRevision"]) is None:
        raise AssertionError("invalid revision")


class ContractBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = LocalSchemaValidator(SCHEMAS)

    def test_schema_documents_are_draft_2020_12_and_refs_are_local(self) -> None:
        for path in sorted(SCHEMAS.glob("*.schema.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], SCHEMA_URI)

            def walk(value: object) -> None:
                if isinstance(value, dict):
                    if "$ref" in value:
                        self.assertFalse(
                            value["$ref"].startswith(("http://", "https://")),
                            path,
                        )
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)

            walk(document)
        for schema_name in (
            "common.schema.json",
            "error.schema.json",
            "list.schema.json",
            "report-route.schema.json",
        ):
            self.assertIn(schema_name, {path.name for path in SCHEMAS.glob("*")})

    def test_manifest_publishes_the_enforced_wire_profile(self) -> None:
        manifest = json.loads((BUNDLE / "contract.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["limits"],
            {
                "stdoutBytes": MAX_STDOUT_BYTES,
                "stderrBytes": MAX_STDERR_BYTES,
                "maxHosts": MAX_HOSTS,
                "maxStringCodePoints": MAX_STRING_CODEPOINTS,
                "maxErrorMessageCodePoints": MAX_ERROR_MESSAGE_CODEPOINTS,
                "maxSourceCodePoints": MAX_SOURCE_CODEPOINTS,
                "maxTimestampMilliseconds": MAX_TIMESTAMP_MS,
            },
        )
        self.assertEqual(manifest["wire"]["encoding"], "UTF-8")
        self.assertEqual(manifest["wire"]["documentCount"], 1)
        self.assertEqual(manifest["wire"]["finalLineFeedBytes"], 1)
        self.assertEqual(manifest["wire"]["trailingBytes"], 0)

    def test_fixture_index_covers_documents_raw_cases_and_supporting_semantics(self) -> None:
        index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["contract"], "host-mesh-v1")
        self.assertEqual(index["schemaVersion"], 1)
        cases = index["cases"]
        self.assertTrue(cases)
        indexed_paths: set[str] = set()
        for case in cases:
            for field in ("command", "fixture", "kind", "schema", "expectedExit", "expected"):
                self.assertIn(field, case, case.get("name"))
            path = BUNDLE / "fixtures" / case["fixture"]
            self.assertTrue(path.is_file(), case["fixture"])
            indexed_paths.add(case["fixture"])
            self.assertIn(case["expected"], ("accept", "reject"))
            self.assertTrue(case["schema"].startswith("schemas/"))
            if case["kind"] == "document":
                value = decode_wire(path.read_bytes())
                self.validator.validate(value, case["schema"].removeprefix("schemas/"))
            else:
                self.assertEqual(case["kind"], "raw")
                with self.assertRaises(ValueError):
                    decode_wire(path.read_bytes())
        for entry in index["supportingFixtures"]:
            self.assertTrue((FIXTURES / entry["fixture"]).is_file(), entry["fixture"])
        valid_paths = {
            path.relative_to(FIXTURES).as_posix()
            for path in (FIXTURES / "valid").glob("*")
            if path.is_file()
        }
        invalid_paths = {
            path.relative_to(FIXTURES).as_posix()
            for path in (FIXTURES / "invalid").glob("*")
            if path.is_file()
        }
        self.assertEqual(
            valid_paths | invalid_paths,
            {name for name in indexed_paths if name.startswith(("valid/", "invalid/"))},
        )

    def test_valid_fixtures_validate_structurally_and_semantically(self) -> None:
        index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
        for case in index["cases"]:
            if case["kind"] != "document":
                continue
            value = decode_wire((FIXTURES / case["fixture"]).read_bytes())
            self.validator.validate(value, case["schema"].removeprefix("schemas/"))
            if case["schema"] == "schemas/list.schema.json":
                _assert_list_semantics(value)

    def test_unknown_fields_and_unknown_typed_codes_are_structurally_allowed(self) -> None:
        document = json.loads(
            (FIXTURES / "valid" / "list-multi-route.json").read_text(encoding="utf-8")
        )
        document["futureField"] = {"producer": "extension"}
        document["sshPolicy"]["futurePolicy"] = True
        document["hosts"][1]["futureHost"] = 1
        document["hosts"][1]["routes"][0]["futureRoute"] = ["x"]
        self.validator.validate(document, "list.schema.json")
        error = {"schemaVersion": 1, "ok": False, "error": {"code": "future_code_7", "message": "later"}}
        self.validator.validate(error, "error.schema.json")
        with self.assertRaises(SchemaValidationError):
            self.validator.validate(
                {"schemaVersion": 1, "ok": False, "error": {"code": "x" * 65, "message": "later"}},
                "error.schema.json",
            )

    def test_semantics_reject_host_id_alias_and_route_collisions(self) -> None:
        source = json.loads(
            (FIXTURES / "valid" / "list-multi-route.json").read_text(encoding="utf-8")
        )
        for field in ("aliases", "routes"):
            with self.subTest(field=field):
                document = json.loads(json.dumps(source))
                if field == "aliases":
                    document["hosts"][2][field] = [document["hosts"][1]["id"]]
                else:
                    document["hosts"][2][field][0]["destination"] = document["hosts"][1]["id"]
                self.validator.validate(document, "list.schema.json")
                with self.assertRaises(AssertionError):
                    _assert_list_semantics(document)

    def test_known_boolean_and_integer_fields_reject_cross_type_values(self) -> None:
        list_document = json.loads(
            (FIXTURES / "valid" / "list-local-only.json").read_text(encoding="utf-8")
        )
        list_document["generatedAt"] = True
        with self.assertRaises(SchemaValidationError):
            self.validator.validate(list_document, "list.schema.json")
        list_document["generatedAt"] = 1
        list_document["hosts"][0]["local"] = 1
        with self.assertRaises(SchemaValidationError):
            self.validator.validate(list_document, "list.schema.json")

        error_document = {
            "schemaVersion": 1,
            "ok": 1,
            "error": {"code": "x", "message": "x"},
        }
        with self.assertRaises(SchemaValidationError):
            self.validator.validate(error_document, "error.schema.json")
        report_document = {"schemaVersion": 1, "ok": 0, "accepted": True}
        with self.assertRaises(SchemaValidationError):
            self.validator.validate(report_document, "report-route.schema.json")
        report_document = {"schemaVersion": 1, "ok": True, "accepted": 0}
        with self.assertRaises(SchemaValidationError):
            self.validator.validate(report_document, "report-route.schema.json")

    def test_bundle_checksums_cover_exact_sorted_file_set_and_define_digest(self) -> None:
        checksum_path = BUNDLE / "SHA256SUMS"
        raw = checksum_path.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        entries: list[tuple[str, str]] = []
        pattern = re.compile(rb"^([0-9a-f]{64})  ([^\x00\r\n]+)\n$")
        for line in raw.splitlines(keepends=True):
            match = pattern.fullmatch(line)
            self.assertIsNotNone(match, line)
            assert match is not None
            entries.append((match.group(2).decode("utf-8"), match.group(1).decode("ascii")))
        names = [name for name, _digest in entries]
        self.assertEqual(names, sorted(names, key=lambda name: name.encode("utf-8")))
        self.assertEqual(len(names), len(set(names)))
        actual_names = sorted(
            (
                path.relative_to(BUNDLE).as_posix()
                for path in BUNDLE.rglob("*")
                if path.is_file() and path != checksum_path
            ),
            key=lambda name: name.encode("utf-8"),
        )
        self.assertEqual(names, actual_names)
        for name, digest in entries:
            self.assertEqual(hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest(), digest)
        # Compute the digest from the manifest's exact bytes, including each
        # line's LF, rather than pinning a second in-repo source of truth.
        bundle_digest = hashlib.sha256(raw).hexdigest()
        self.assertRegex(bundle_digest, r"^[0-9a-f]{64}$")

    def test_public_producer_emits_strict_bounded_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home = root / "config"
            state_home = root / "state"
            config_path = config_home / "rofi-ssh-plus" / "config.toml"
            config_path.parent.mkdir(parents=True)
            shutil.copyfile(FIXTURES / "config-multi-route.toml", config_path)
            environment = {
                "XDG_CONFIG_HOME": str(config_home),
                "XDG_STATE_HOME": str(state_home),
            }
            output = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(["mesh", "list", "--json"], environ=environment, stdout=output)
                self.assertEqual(result, 0)
                output.seek(0)
                raw = output.read().encode("utf-8")
            finally:
                output.close()
            value = decode_wire(raw)
            self.validator.validate(value, "list.schema.json")
            _assert_list_semantics(value)
            self.assertLessEqual(len(raw), MAX_STDOUT_BYTES)

    def test_subprocess_exit_and_body_consistency_and_stderr_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                **dict(os.environ),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_STATE_HOME": str(root / "state"),
            }
            config_path = Path(environment["XDG_CONFIG_HOME"]) / "rofi-ssh-plus" / "config.toml"
            config_path.parent.mkdir(parents=True)
            shutil.copyfile(FIXTURES / "config-local-only.toml", config_path)
            good = subprocess.run(
                ["python3", "bin/rofi-ssh-plus", "mesh", "list", "--json"],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(good.returncode, 0)
            self.assertLessEqual(len(good.stdout), MAX_STDOUT_BYTES)
            self.assertLessEqual(len(good.stderr), MAX_STDERR_BYTES)
            value = decode_wire(good.stdout)
            self.validator.validate(value, "list.schema.json")
            invalid = subprocess.run(
                [
                    "python3",
                    "bin/rofi-ssh-plus",
                    "mesh",
                    "list",
                    "--json",
                    "--unknown",
                    "x" * 100_000,
                ],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertLessEqual(len(invalid.stderr), MAX_STDERR_BYTES)
            error = decode_wire(invalid.stdout)
            self.validator.validate(error, "error.schema.json")
            self.assertFalse(error["ok"])

    def test_configuration_and_response_bounds_fail_small_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home = root / "config"
            state_home = root / "state"
            config_path = config_home / "rofi-ssh-plus" / "config.toml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                'schema_version = 1\nlocal_id = "alpha"\nlocal_display = "' + "x" * (MAX_STRING_CODEPOINTS + 1) + '"\n',
                encoding="utf-8",
            )
            environment = {"XDG_CONFIG_HOME": str(config_home), "XDG_STATE_HOME": str(state_home)}
            output = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(["mesh", "list", "--json"], environ=environment, stdout=output)
                output.seek(0)
                raw = output.read().encode("utf-8")
            finally:
                output.close()
            self.assertNotEqual(result, 0)
            error = decode_wire(raw)
            self.validator.validate(error, "error.schema.json")
            self.assertEqual(error["error"]["code"], "invalid_config")
            self.assertLessEqual(len(raw), MAX_STDOUT_BYTES)

            too_many = [
                f'[[hosts]]\nid = "host-{index}"\nroutes = ["route-{index}"]\n'
                for index in range(MAX_HOSTS)
            ]
            config_path.write_text(
                'schema_version = 1\nlocal_id = "alpha"\n' + "".join(too_many),
                encoding="utf-8",
            )
            output = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(["mesh", "list", "--json"], environ=environment, stdout=output)
                output.seek(0)
                raw = output.read().encode("utf-8")
            finally:
                output.close()
            self.assertNotEqual(result, 0)
            error = decode_wire(raw)
            self.validator.validate(error, "error.schema.json")
            self.assertEqual(error["error"]["code"], "invalid_config")

            remotes = [
                f'[[hosts]]\nid = "host-{index}"\ndisplay = "{index}"\nroutes = ["route-{index}-' + "r" * 5_000 + '"]\n'
                for index in range(MAX_HOSTS - 1)
            ]
            config_path.write_text(
                'schema_version = 1\nlocal_id = "alpha"\n' + "".join(remotes),
                encoding="utf-8",
            )
            output = tempfile.SpooledTemporaryFile(max_size=2 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(["mesh", "list", "--json"], environ=environment, stdout=output)
                output.seek(0)
                raw = output.read().encode("utf-8")
            finally:
                output.close()
            self.assertNotEqual(result, 0)
            error = decode_wire(raw)
            self.validator.validate(error, "error.schema.json")
            self.assertEqual(error["error"]["code"], "invalid_config")
            self.assertLessEqual(len(raw), MAX_STDOUT_BYTES)

    def test_report_producer_success_errors_and_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home = root / "config"
            state_home = root / "state"
            config_path = config_home / "rofi-ssh-plus" / "config.toml"
            config_path.parent.mkdir(parents=True)
            shutil.copyfile(FIXTURES / "config-multi-route.toml", config_path)
            environment = {"XDG_CONFIG_HOME": str(config_home), "XDG_STATE_HOME": str(state_home)}
            listing = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                self.assertEqual(main(["mesh", "list", "--json"], environ=environment, stdout=listing), 0)
                listing.seek(0)
                revision = json.loads(listing.read())["meshRevision"]
            finally:
                listing.close()
            args = [
                "mesh",
                "report-route",
                "--json",
                "--host",
                "beta",
                "--route",
                "beta-vpn.test",
                "--status",
                "reachable",
                "--source",
                "fixture",
                "--mesh-revision",
                revision,
                "--observed-at",
                str(current_time_ms() - 1),
            ]
            output = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(args, environ=environment, stdout=output)
                output.seek(0)
                raw = output.read().encode("utf-8")
            finally:
                output.close()
            self.assertEqual(result, 0)
            self.validator.validate(decode_wire(raw), "report-route.schema.json")
            self.assertTrue(decode_wire(raw)["accepted"])
            output = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(args, environ=environment, stdout=output)
                output.seek(0)
                duplicate = decode_wire(output.read().encode("utf-8"))
            finally:
                output.close()
            self.assertEqual(result, 0)
            self.validator.validate(duplicate, "report-route.schema.json")
            self.assertFalse(duplicate["accepted"])
            overlong = args.copy()
            overlong[overlong.index("fixture")] = "x" * 65
            output = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+", encoding="utf-8")
            try:
                result = main(overlong, environ=environment, stdout=output)
                output.seek(0)
                error = decode_wire(output.read().encode("utf-8"))
            finally:
                output.close()
            self.assertNotEqual(result, 0)
            self.validator.validate(error, "error.schema.json")
            self.assertEqual(error["error"]["code"], "invalid_input")

    def test_contract_bundle_contains_no_private_names(self) -> None:
        forbidden = (b"/home/", b"bryan", b"dankmaterialshell", b".ssh/")
        for path in BUNDLE.rglob("*"):
            if not path.is_file() or path.name == "SHA256SUMS":
                continue
            lowered = path.read_bytes().lower()
            for value in forbidden:
                self.assertNotIn(value, lowered, path)


if __name__ == "__main__":
    unittest.main()

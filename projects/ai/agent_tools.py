import json
from pathlib import Path
import subprocess
import tempfile
import os
from pathlib import Path
import subprocess
import tempfile
import io
import tarfile
import requests

from projects.integrations.base import IntegrationError
from django.core.files.base import ContentFile
import os
from weakref import ref
from projects.models import AgentRunEvent, AgentRunLog, ConnectedAccount, AgentApprovalRequest, GitHubRepository
from projects.integrations import get_user_integration, github
from projects.integrations.policy import (
    ConnectedAppPermissionError,
    validate_connected_app_request,
)

import base64
import json
import hashlib
from projects.models import (
    AgentRun,
    AgentWorkspaceRecord,
    ConnectedAccount,
    GitHubRepository,
)
import shlex
from django.db import transaction
from django.utils import timezone
from projects.integrations import (
    get_user_integration,
)
import json

from projects.models import (
    AgentApprovalRequest,
)
class AgentWorkspace:
    def __init__(self, run_id):
        self.run_id = run_id

        run = AgentRun.objects.get(
            pk=run_id,
        )

        base_dir = (
            Path(tempfile.gettempdir())
            / "projivo_agents"
        )

        base_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.root = (
            base_dir
            / f"run_{run_id}"
        )

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.record, _ = (
            AgentWorkspaceRecord.objects.get_or_create(
                run=run,
                defaults={
                    "workspace_path": str(
                        self.root.resolve()
                    ),
                },
            )
        )

        if (
            self.record.workspace_path
            != str(self.root.resolve())
        ):
            self.record.workspace_path = str(
                self.root.resolve()
            )

            self.record.save(
                update_fields=[
                    "workspace_path",
                    "updated_at",
                ]
            )
    def _safe_path(self, relative_path):
        relative_path = relative_path.lstrip("/")

        path = (
            self.root
            / relative_path
        ).resolve()

        root = self.root.resolve()

        if (
            path != root
            and root not in path.parents
        ):
            raise ValueError(
                "Path escapes agent workspace."
            )

        return path

    def _container_name(self):
        return (
            f"projivo-agent-run-{self.run_id}"
        )

    def _container_exists(self):
        result = subprocess.run(
            [
                "docker",
                "inspect",
                self._container_name(),
            ],
            capture_output=True,
            text=True,
        )

        return result.returncode == 0

    def _container_running(self):
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                self._container_name(),
            ],
            capture_output=True,
            text=True,
        )

        return (
            result.returncode == 0
            and result.stdout.strip() == "true"
        )

    def ensure_container(self):
        container_name = (
            self._container_name()
        )

        if self._container_running():
            return container_name

        if self._container_exists():
            subprocess.run(
                [
                    "docker",
                    "rm",
                    "-f",
                    container_name,
                ],
                capture_output=True,
                text=True,
            )

        completed = subprocess.run(
            [
                "docker",
                "run",
                "-d",

                "--name",
                container_name,

                "--network",
                "none",

                "--memory",
                "512m",

                "--cpus",
                "1",

                "--pids-limit",
                "128",

                "--cap-drop",
                "ALL",

                "--security-opt",
                "no-new-privileges",

                "--user",
                f"{os.getuid()}:{os.getgid()}",

                "--env",
                "HOME=/tmp/projivo-home",

                "-v",
                (
                    f"{self.root.resolve()}"
                    ":/workspace"
                ),

                "-w",
                "/workspace",

                "projivo-agent:dev",

                "bash",
                "-lc",
                (
                    'mkdir -p "$HOME" '
                    "&& exec sleep infinity"
                ),
            ],
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "Unable to start agent container: "
                + completed.stderr
            )

        return container_name

    def stop_container(self):
        container_name = (
            self._container_name()
        )

        if not self._container_exists():
            return

        subprocess.run(
            [
                "docker",
                "rm",
                "-f",
                container_name,
            ],
            capture_output=True,
            text=True,
        )

    def list_files(self, path="."):
        target = self._safe_path(path)

        if not target.exists():
            raise FileNotFoundError(path)

        if not target.is_dir():
            raise ValueError(
                "Path is not a directory."
            )

        items = []

        for item in sorted(
            target.iterdir(),
            key=lambda x: x.name.lower(),
        ):
            relative = item.relative_to(
                self.root
            )

            items.append(
                {
                    "name": item.name,
                    "path": str(relative),
                    "type": (
                        "directory"
                        if item.is_dir()
                        else "file"
                    ),
                }
            )

        return items

    def read_file(self, path):
        target = self._safe_path(path)

        if not target.exists():
            raise FileNotFoundError(path)

        if not target.is_file():
            raise ValueError(
                "Path is not a file."
            )

        return target.read_text(
            encoding="utf-8",
            errors="replace",
        )

    def write_file(
        self,
        path,
        content,
    ):
        target = self._safe_path(path)

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            content,
            encoding="utf-8",
        )

        return {
            "path": str(
                target.relative_to(
                    self.root
                )
            ),
            "bytes": len(
                content.encode("utf-8")
            ),
        }

    def run_command(
        self,
        command,
        max_output_chars=10000,
    ):
        container_name = (
            self.ensure_container()
        )

        completed = subprocess.run(
            [
                "docker",
                "exec",
                "-w",
                "/workspace",
                container_name,
                "bash",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        return {
            "returncode": (
                completed.returncode
            ),
            "stdout": (
                completed.stdout[
                    -max_output_chars:
                ]
            ),
            "stderr": (
                completed.stderr[
                    -max_output_chars:
                ]
            ),
        }
MAX_WORKSPACE_SNAPSHOT_BYTES = (
    20 * 1024 * 1024
)

MAX_WORKSPACE_SNAPSHOT_FILES = 500


def build_non_repository_snapshot(
    *,
    workspace,
):
    """
    Create a compressed snapshot of a non-repository
    agent workspace.

    Returns the archive bytes plus a manifest describing
    the files included in the snapshot.
    """

    files = []

    for path in sorted(
        workspace.root.rglob("*"),
    ):
        if not path.is_file():
            continue

        relative_path = path.relative_to(
            workspace.root
        )

        # Internal Projivo recovery data should not
        # become part of the user's workspace snapshot.
        if (
            relative_path.parts
            and relative_path.parts[0]
            == ".projivo"
        ):
            continue

        files.append(
            (
                path,
                relative_path,
            )
        )

    if (
        len(files)
        > MAX_WORKSPACE_SNAPSHOT_FILES
    ):
        raise ValueError(
            "Agent workspace contains too many "
            "files to preserve safely."
        )

    manifest_files = []
    total_uncompressed_bytes = 0

    buffer = io.BytesIO()

    with tarfile.open(
        fileobj=buffer,
        mode="w:gz",
    ) as archive:
        for path, relative_path in files:
            data = path.read_bytes()

            total_uncompressed_bytes += len(
                data
            )

            if (
                total_uncompressed_bytes
                > MAX_WORKSPACE_SNAPSHOT_BYTES
            ):
                raise ValueError(
                    "Agent workspace exceeds the "
                    "20 MB preservation limit."
                )

            archive.add(
                path,
                arcname=relative_path.as_posix(),
                recursive=False,
            )

            manifest_files.append(
                {
                    "path": (
                        relative_path.as_posix()
                    ),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(
                        data
                    ).hexdigest(),
                }
            )

    snapshot = buffer.getvalue()

    return {
        "snapshot": snapshot,
        "manifest": {
            "version": 1,
            "file_count": len(
                manifest_files
            ),
            "total_bytes": (
                total_uncompressed_bytes
            ),
            "compressed_bytes": len(
                snapshot
            ),
            "files": manifest_files,
        },
    }
@transaction.atomic
def preserve_workspace_state(
    *,
    workspace,
    run,
):
    """
    Preserve recoverable agent workspace state.

    Non-repository workspaces:
        - Save the workspace as a compressed tar.gz snapshot.
        - Store a manifest containing file paths, sizes,
          and SHA-256 hashes.

    Repository-backed workspaces:
        - Preserve unsynced Git changes as a binary patch.
        - Record changed/untracked files.
        - Preserve repository/base commit metadata.

    The temporary Docker container and local workspace can
    then disappear without losing recoverable agent work.
    """

    record = workspace.record
    repo_name = record.repository_name

    # =====================================================
    # NON-REPOSITORY WORKSPACE
    # =====================================================

    if not repo_name:
        snapshot_result = (
            build_non_repository_snapshot(
                workspace=workspace,
            )
        )

        snapshot_bytes = (
            snapshot_result["snapshot"]
        )

        manifest = (
            snapshot_result["manifest"]
        )

        # Remove any previous stored snapshot.
        if record.workspace_snapshot:
            record.workspace_snapshot.delete(
                save=False,
            )

        snapshot_name = (
            f"agent_run_{run.pk}.tar.gz"
        )

        record.workspace_snapshot.save(
            snapshot_name,
            ContentFile(snapshot_bytes),
            save=False,
        )

        record.workspace_snapshot_manifest = (
            manifest
        )

        # Standalone workspaces do not use
        # repository recovery fields.
        record.patch = ""
        record.manifest = {}

        record.status = (
            AgentWorkspaceRecord
            .Status
            .PRESERVED
        )

        record.preserved_at = (
            timezone.now()
        )

        record.save(
            update_fields=[
                "workspace_snapshot",
                "workspace_snapshot_manifest",
                "patch",
                "manifest",
                "status",
                "preserved_at",
                "updated_at",
            ]
        )

        AgentRunLog.objects.create(
            run=run,
            message=(
                "Agent workspace preserved. "
                f"Files: "
                f"{manifest['file_count']}. "
                f"Snapshot bytes: "
                f"{len(snapshot_bytes)}."
            ),
        )

        return {
            "preserved": True,
            "repository": False,
            "snapshot": True,
            "snapshot_bytes": len(
                snapshot_bytes
            ),
            "workspace_bytes": (
                manifest["total_bytes"]
            ),
            "file_count": (
                manifest["file_count"]
            ),
            "changed_files": [
                item["path"]
                for item
                in manifest["files"]
            ],
        }

    # =====================================================
    # REPOSITORY-BACKED WORKSPACE
    # =====================================================

    repo_relative_path = repo_name

    repo_path = workspace._safe_path(
        repo_relative_path
    )

    # -----------------------------------------------------
    # Repository directory disappeared
    # -----------------------------------------------------

    if not repo_path.exists():
        record.status = (
            AgentWorkspaceRecord
            .Status
            .PRESERVED
        )

        record.preserved_at = (
            timezone.now()
        )

        record.save(
            update_fields=[
                "status",
                "preserved_at",
                "updated_at",
            ]
        )

        AgentRunLog.objects.create(
            run=run,
            message=(
                "Agent workspace preserved, but "
                "the repository directory was "
                "missing."
            ),
        )

        return {
            "preserved": True,
            "repository": True,
            "workspace_missing": True,
            "patch_bytes": 0,
            "changed_files": [],
        }

    # -----------------------------------------------------
    # Tracked modifications/deletions
    # -----------------------------------------------------

    diff_result = workspace.run_command(
        command=(
            f"cd {shlex.quote(repo_relative_path)} "
            "&& git diff "
            "--binary "
            "--no-ext-diff"
        ),
        max_output_chars=2_200_000,
    )

    if diff_result["returncode"] != 0:
        raise RuntimeError(
            "Could not generate workspace patch: "
            + diff_result.get(
                "stderr",
                "",
            )
        )

    patch = diff_result.get(
        "stdout",
        "",
    )

    # -----------------------------------------------------
    # Find untracked files
    # -----------------------------------------------------

    untracked_result = (
        workspace.run_command(
            command=(
                f"cd "
                f"{shlex.quote(repo_relative_path)} "
                "&& git ls-files "
                "--others "
                "--exclude-standard"
            ),
            max_output_chars=100_000,
        )
    )

    if (
        untracked_result["returncode"]
        != 0
    ):
        raise RuntimeError(
            "Could not inspect untracked files: "
            + untracked_result.get(
                "stderr",
                "",
            )
        )

    untracked_files = [
        path.strip()
        for path
        in untracked_result.get(
            "stdout",
            "",
        ).splitlines()
        if path.strip()
    ]

    # -----------------------------------------------------
    # Add untracked files to patch
    # -----------------------------------------------------

    for relative_path in untracked_files:
        safe_relative = shlex.quote(
            relative_path
        )

        result = workspace.run_command(
            command=(
                f"cd "
                f"{shlex.quote(repo_relative_path)} "
                "&& git diff "
                "--binary "
                "--no-index "
                "/dev/null "
                f"{safe_relative} "
                "|| true"
            ),
            max_output_chars=2_200_000,
        )

        file_patch = result.get(
            "stdout",
            "",
        )

        if file_patch:
            if (
                patch
                and not patch.endswith("\n")
            ):
                patch += "\n"

            patch += file_patch

    # -----------------------------------------------------
    # Limit stored patch size
    # -----------------------------------------------------

    max_patch_bytes = (
        2 * 1024 * 1024
    )

    encoded_patch = patch.encode(
        "utf-8",
        errors="replace",
    )

    patch_truncated = False

    if (
        len(encoded_patch)
        > max_patch_bytes
    ):
        encoded_patch = encoded_patch[
            :max_patch_bytes
        ]

        patch = encoded_patch.decode(
            "utf-8",
            errors="ignore",
        )

        patch_truncated = True

    # -----------------------------------------------------
    # Inspect changed files
    # -----------------------------------------------------

    status_result = (
        workspace.run_command(
            command=(
                f"cd "
                f"{shlex.quote(repo_relative_path)} "
                "&& git status --porcelain"
            ),
            max_output_chars=100_000,
        )
    )

    changed_files = []

    if status_result["returncode"] == 0:
        for line in status_result.get(
            "stdout",
            "",
        ).splitlines():
            line = line.rstrip()

            if not line:
                continue

            path = (
                line[3:]
                if len(line) > 3
                else line
            )

            if " -> " in path:
                path = path.split(
                    " -> ",
                    1,
                )[1]

            if path:
                changed_files.append(
                    path
                )

    # -----------------------------------------------------
    # Build repository manifest
    # -----------------------------------------------------

    manifest = {
        "repository": (
            f"{record.repository_owner}/"
            f"{record.repository_name}"
        ),
        "branch": (
            record.repository_branch
        ),
        "base_commit_sha": (
            record.base_commit_sha
        ),
        "last_synced_commit_sha": (
            record.last_synced_commit_sha
        ),
        "changed_files": sorted(
            set(changed_files)
        ),
        "untracked_files": sorted(
            set(untracked_files)
        ),
        "patch_truncated": (
            patch_truncated
        ),
    }

    # -----------------------------------------------------
    # Repository workspaces should not retain an old
    # standalone snapshot.
    # -----------------------------------------------------

    if record.workspace_snapshot:
        record.workspace_snapshot.delete(
            save=False,
        )

    record.workspace_snapshot = ""
    record.workspace_snapshot_manifest = {}

    record.patch = patch
    record.manifest = manifest

    record.status = (
        AgentWorkspaceRecord
        .Status
        .PRESERVED
    )

    record.preserved_at = (
        timezone.now()
    )

    record.save(
        update_fields=[
            "workspace_snapshot",
            "workspace_snapshot_manifest",
            "patch",
            "manifest",
            "status",
            "preserved_at",
            "updated_at",
        ]
    )

    patch_bytes = len(
        patch.encode(
            "utf-8",
            errors="replace",
        )
    )

    AgentRunLog.objects.create(
        run=run,
        message=(
            "Agent workspace preserved. "
            f"Changed files: "
            f"{len(changed_files)}. "
            f"Patch bytes: "
            f"{patch_bytes}."
        ),
    )

    return {
        "preserved": True,
        "repository": True,
        "patch_bytes": (
            patch_bytes
        ),
        "patch_truncated": (
            patch_truncated
        ),
        "changed_files": sorted(
            set(changed_files)
        ),
        "untracked_files": sorted(
            set(untracked_files)
        ),
    }
def restore_workspace_state(
    *,
    workspace,
    source_run,
    target_run,
):
    """
    Restore preserved workspace state from source_run
    into target_run's fresh workspace.

    Non-repository workspaces are restored from their
    compressed snapshot and verified against the stored
    manifest.

    Repository-backed workspaces are restored by loading
    the current repository and applying the preserved
    Git patch.
    """

    try:
        source_record = (
            source_run.workspace_record
        )
    except AgentWorkspaceRecord.DoesNotExist:
        raise ValueError(
            "The source agent run has no "
            "preserved workspace."
        )

    if (
        source_record.status
        != AgentWorkspaceRecord.Status.PRESERVED
    ):
        raise ValueError(
            "The source workspace has not "
            "been preserved."
        )

    # =====================================================
    # NON-REPOSITORY WORKSPACE
    # =====================================================

    if not source_record.repository_name:
        target_record = workspace.record

        manifest = (
            source_record
            .workspace_snapshot_manifest
            or {}
        )

        expected_files = (
            manifest.get("files", [])
        )

        # -------------------------------------------------
        # Backward compatibility:
        #
        # Older preserved runs may have no snapshot because
        # they were created before standalone persistence
        # existed.
        # -------------------------------------------------

        if not source_record.workspace_snapshot:
            target_record.status = (
                AgentWorkspaceRecord.Status.ACTIVE
            )

            target_record.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            AgentRunLog.objects.create(
                run=target_run,
                message=(
                    "Recovered non-repository workspace "
                    f"from AgentRun {source_run.pk}. "
                    "No saved workspace snapshot existed."
                ),
            )

            return {
                "restored": True,
                "snapshot_restored": False,
                "repository": None,
                "branch": None,
                "source_run_id": source_run.pk,
                "changed_files": [],
                "message": (
                    "The previous run had no saved "
                    "standalone workspace files."
                ),
                "load_result": None,
            }

        # -------------------------------------------------
        # Validate manifest
        # -------------------------------------------------

        if (
            manifest.get("version")
            != 1
        ):
            raise ValueError(
                "Unsupported workspace snapshot "
                "manifest version."
            )

        if not isinstance(
            expected_files,
            list,
        ):
            raise ValueError(
                "Workspace snapshot manifest is invalid."
            )

        if (
            len(expected_files)
            > MAX_WORKSPACE_SNAPSHOT_FILES
        ):
            raise ValueError(
                "Workspace snapshot contains too many "
                "files to restore safely."
            )

        declared_total_bytes = (
            manifest.get(
                "total_bytes",
                0,
            )
        )

        if (
            not isinstance(
                declared_total_bytes,
                int,
            )
            or declared_total_bytes < 0
            or declared_total_bytes
            > MAX_WORKSPACE_SNAPSHOT_BYTES
        ):
            raise ValueError(
                "Workspace snapshot size is invalid."
            )

        # -------------------------------------------------
        # Read snapshot from Django storage.
        #
        # Do not rely on .path because production storage
        # may eventually be S3/object storage.
        # -------------------------------------------------

        source_record.workspace_snapshot.open(
            "rb"
        )

        try:
            snapshot_bytes = (
                source_record
                .workspace_snapshot
                .read()
            )
        finally:
            source_record.workspace_snapshot.close()

        if not snapshot_bytes:
            raise ValueError(
                "The preserved workspace snapshot "
                "is empty."
            )

        # Keep the compressed input bounded too.
        if (
            len(snapshot_bytes)
            > MAX_WORKSPACE_SNAPSHOT_BYTES
        ):
            raise ValueError(
                "The preserved workspace snapshot "
                "is too large to restore safely."
            )

        # -------------------------------------------------
        # Build expected manifest lookup
        # -------------------------------------------------

        expected_by_path = {}

        for item in expected_files:
            if not isinstance(item, dict):
                raise ValueError(
                    "Workspace snapshot manifest "
                    "contains an invalid file entry."
                )

            relative_path = item.get(
                "path"
            )

            expected_size = item.get(
                "bytes"
            )

            expected_sha256 = item.get(
                "sha256"
            )

            if (
                not isinstance(
                    relative_path,
                    str,
                )
                or not relative_path
            ):
                raise ValueError(
                    "Workspace snapshot manifest "
                    "contains an invalid path."
                )

            if (
                not isinstance(
                    expected_size,
                    int,
                )
                or expected_size < 0
            ):
                raise ValueError(
                    "Workspace snapshot manifest "
                    "contains an invalid file size."
                )

            if (
                not isinstance(
                    expected_sha256,
                    str,
                )
                or len(expected_sha256) != 64
            ):
                raise ValueError(
                    "Workspace snapshot manifest "
                    "contains an invalid SHA-256 hash."
                )

            if (
                relative_path
                in expected_by_path
            ):
                raise ValueError(
                    "Workspace snapshot manifest "
                    "contains duplicate paths."
                )

            # _safe_path performs the important
            # path traversal validation.
            workspace._safe_path(
                relative_path
            )

            expected_by_path[
                relative_path
            ] = item

        if (
            manifest.get("file_count")
            != len(expected_by_path)
        ):
            raise ValueError(
                "Workspace snapshot manifest "
                "file count does not match."
            )

        # -------------------------------------------------
        # Open archive and validate ALL members before
        # writing anything.
        # -------------------------------------------------

        snapshot_buffer = io.BytesIO(
            snapshot_bytes
        )

        try:
            archive = tarfile.open(
                fileobj=snapshot_buffer,
                mode="r:gz",
            )
        except tarfile.TarError as exc:
            raise ValueError(
                "The preserved workspace snapshot "
                "is not a valid tar.gz archive."
            ) from exc

        restored_files = []
        total_restored_bytes = 0

        try:
            members = archive.getmembers()

            archive_files = {}

            for member in members:
                # We only preserve regular files.
                #
                # Reject links/devices/etc rather than
                # allowing tar semantics to create them.
                if not member.isfile():
                    raise ValueError(
                        "Workspace snapshot contains "
                        "an unsupported archive entry."
                    )

                relative_path = member.name

                if not relative_path:
                    raise ValueError(
                        "Workspace snapshot contains "
                        "an invalid empty path."
                    )

                # Explicitly reject absolute paths.
                if Path(relative_path).is_absolute():
                    raise ValueError(
                        "Workspace snapshot contains "
                        "an absolute path."
                    )

                # This also rejects ../../ escapes after
                # resolving against workspace.root.
                workspace._safe_path(
                    relative_path
                )

                if (
                    relative_path
                    in archive_files
                ):
                    raise ValueError(
                        "Workspace snapshot contains "
                        "duplicate archive paths."
                    )

                if (
                    relative_path
                    not in expected_by_path
                ):
                    raise ValueError(
                        "Workspace snapshot contains "
                        "a file that is not present "
                        "in its manifest."
                    )

                archive_files[
                    relative_path
                ] = member

            # Every manifest file must exist in archive.
            if (
                set(archive_files)
                != set(expected_by_path)
            ):
                raise ValueError(
                    "Workspace snapshot archive does "
                    "not match its manifest."
                )

            # ---------------------------------------------
            # Extract manually and verify BEFORE writing.
            # ---------------------------------------------

            for (
                relative_path,
                member,
            ) in archive_files.items():

                expected = (
                    expected_by_path[
                        relative_path
                    ]
                )

                extracted = (
                    archive.extractfile(
                        member
                    )
                )

                if extracted is None:
                    raise ValueError(
                        "Could not read a file from "
                        "the workspace snapshot."
                    )

                raw = extracted.read(
                    MAX_WORKSPACE_SNAPSHOT_BYTES
                    + 1
                )

                if (
                    len(raw)
                    > MAX_WORKSPACE_SNAPSHOT_BYTES
                ):
                    raise ValueError(
                        "A workspace snapshot file "
                        "exceeds the restore limit."
                    )

                if (
                    len(raw)
                    != expected["bytes"]
                ):
                    raise ValueError(
                        "Workspace snapshot file size "
                        "verification failed for "
                        f"{relative_path}."
                    )

                actual_sha256 = (
                    hashlib.sha256(
                        raw
                    ).hexdigest()
                )

                if (
                    actual_sha256
                    != expected["sha256"]
                ):
                    raise ValueError(
                        "Workspace snapshot integrity "
                        "verification failed for "
                        f"{relative_path}."
                    )

                total_restored_bytes += (
                    len(raw)
                )

                if (
                    total_restored_bytes
                    > MAX_WORKSPACE_SNAPSHOT_BYTES
                ):
                    raise ValueError(
                        "Restored workspace exceeds "
                        "the maximum allowed size."
                    )

                target_path = (
                    workspace._safe_path(
                        relative_path
                    )
                )

                target_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                target_path.write_bytes(
                    raw
                )

                restored_files.append(
                    relative_path
                )

        finally:
            archive.close()

        # -------------------------------------------------
        # Final verification against manifest
        # -------------------------------------------------

        if (
            total_restored_bytes
            != declared_total_bytes
        ):
            raise ValueError(
                "Restored workspace total size "
                "does not match its manifest."
            )

        for relative_path in restored_files:
            expected = (
                expected_by_path[
                    relative_path
                ]
            )

            restored_path = (
                workspace._safe_path(
                    relative_path
                )
            )

            if not restored_path.is_file():
                raise ValueError(
                    "Workspace restoration failed "
                    f"for {relative_path}."
                )

            actual_sha256 = hashlib.sha256(
                restored_path.read_bytes()
            ).hexdigest()

            if (
                actual_sha256
                != expected["sha256"]
            ):
                raise ValueError(
                    "Restored workspace verification "
                    "failed for "
                    f"{relative_path}."
                )

        # -------------------------------------------------
        # Mark new workspace active
        # -------------------------------------------------

        target_record.status = (
            AgentWorkspaceRecord.Status.ACTIVE
        )

        target_record.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        AgentRunLog.objects.create(
            run=target_run,
            message=(
                "Recovered standalone workspace "
                f"from AgentRun {source_run.pk}. "
                f"Restored files: "
                f"{len(restored_files)}."
            ),
        )

        return {
            "restored": True,
            "snapshot_restored": True,
            "patch_applied": False,
            "repository": None,
            "branch": None,
            "source_run_id": source_run.pk,
            "changed_files": sorted(
                restored_files
            ),
            "restored_files": sorted(
                restored_files
            ),
            "restored_bytes": (
                total_restored_bytes
            ),
            "message": (
                "Standalone workspace snapshot "
                "restored successfully."
            ),
            "load_result": None,
        }

    # =====================================================
    # REPOSITORY-BACKED WORKSPACE
    # =====================================================

    patch = source_record.patch or ""

    # Load a fresh copy of the project's current
    # GitHub repository into the new workspace.
    load_result = load_project_repository(
        workspace=workspace,
        run=target_run,
    )

    target_record = workspace.record

    source_repository = (
        f"{source_record.repository_owner}/"
        f"{source_record.repository_name}"
    )

    target_repository = (
        f"{target_record.repository_owner}/"
        f"{target_record.repository_name}"
    )

    if target_repository != source_repository:
        raise ValueError(
            "The project's linked repository changed "
            "since the original agent run. "
            f"Expected {source_repository}, "
            f"but found {target_repository}."
        )

    if (
        target_record.repository_branch
        != source_record.repository_branch
    ):
        raise ValueError(
            "The project's repository branch changed "
            "since the original agent run. "
            f"Expected "
            f"{source_record.repository_branch}, "
            f"but found "
            f"{target_record.repository_branch}."
        )

    # No unsynced work means there is nothing
    # to restore.
    if not patch.strip():
        AgentRunLog.objects.create(
            run=target_run,
            message=(
                "Recovered repository workspace "
                f"from AgentRun {source_run.pk}. "
                "No unsynced changes needed restoration."
            ),
        )

        return {
            "restored": True,
            "patch_applied": False,
            "repository": target_repository,
            "branch": (
                target_record.repository_branch
            ),
            "source_run_id": source_run.pk,
            "changed_files": [],
            "message": (
                "The previous run had no "
                "unsynced repository changes."
            ),
            "load_result": load_result,
        }

    if source_record.manifest.get(
        "patch_truncated",
        False,
    ):
        raise ValueError(
            "The preserved workspace patch was "
            "truncated and cannot be safely "
            "restored automatically."
        )

    repository_name = (
        target_record.repository_name
    )

    patch_path = (
        workspace.root
        / ".projivo"
        / "recovery.patch"
    )

    patch_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    patch_path.write_text(
        patch,
        encoding="utf-8",
    )

    # Verify before modifying repository.
    check_result = workspace.run_command(
        command=(
            f"cd {shlex.quote(repository_name)} "
            "&& git apply --check "
            "../.projivo/recovery.patch"
        ),
        max_output_chars=100_000,
    )

    if check_result["returncode"] != 0:
        raise ValueError(
            "The preserved workspace changes "
            "cannot be cleanly applied to the "
            "current repository. Manual conflict "
            "resolution is required. "
            + (
                check_result.get(
                    "stderr",
                    "",
                )
                or check_result.get(
                    "stdout",
                    "",
                )
            )
        )

    apply_result = workspace.run_command(
        command=(
            f"cd {shlex.quote(repository_name)} "
            "&& git apply "
            "../.projivo/recovery.patch"
        ),
        max_output_chars=100_000,
    )

    if apply_result["returncode"] != 0:
        raise RuntimeError(
            "The recovery patch passed validation "
            "but could not be applied: "
            + (
                apply_result.get(
                    "stderr",
                    "",
                )
                or apply_result.get(
                    "stdout",
                    "",
                )
            )
        )

    status_result = workspace.run_command(
        command=(
            f"cd {shlex.quote(repository_name)} "
            "&& git status --porcelain"
        ),
        max_output_chars=100_000,
    )

    if status_result["returncode"] != 0:
        raise RuntimeError(
            "Workspace recovery succeeded, but "
            "the restored repository status "
            "could not be inspected."
        )

    changed_files = []

    for line in status_result[
        "stdout"
    ].splitlines():
        line = line.rstrip()

        if not line:
            continue

        path = (
            line[3:]
            if len(line) > 3
            else line
        )

        if " -> " in path:
            path = path.split(
                " -> ",
                1,
            )[1]

        if path:
            changed_files.append(
                path
            )

    AgentRunLog.objects.create(
        run=target_run,
        message=(
            "Recovered preserved workspace "
            f"from AgentRun {source_run.pk}. "
            f"Restored files: "
            f"{len(changed_files)}."
        ),
    )

    return {
        "restored": True,
        "patch_applied": True,
        "repository": target_repository,
        "branch": (
            target_record.repository_branch
        ),
        "source_run_id": source_run.pk,
        "changed_files": sorted(
            set(changed_files)
        ),
        "load_result": load_result,
    }
CONNECTED_APP_TOOL = {
    "type": "function",
    "name": "connected_app_request",
    "description": (
        "Make an authenticated API request to one of the "
        "user's connected applications. Use this instead "
        "of searching the terminal for API credentials."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "provider": {
                "type": "string",
                "enum": ["github"],
            },
            "method": {
                "type": "string",
                "enum": [
                    "GET",
                    "POST",
                    "PATCH",
                    "PUT",
                ],
            },
            "path": {
                "type": "string",
                "description": (
                    "Provider API path, for example "
                    "/user/repos."
                ),
            },
            "body_json": {
                "type": "string",
                "description": (
                    "JSON object encoded as a string. "
                    "Use '{}' when no request body is needed."
                ),
            },
        },
        "required": [
            "provider",
            "method",
            "path",
            "body_json",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}
LIST_CONNECTED_APPS_TOOL = {
    "type": "function",
    "name": "list_connected_apps",
    "description": (
        "List external services the current user has connected "
        "to Projivo."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    "strict": True,
}
REQUEST_USER_APPROVAL_TOOL = {
    "type": "function",
    "name": "request_user_approval",
    "description": (
        "Request explicit user approval before performing "
        "a consequential or sensitive action. Use this when "
        "an action requires confirmation before execution. "
        "Calling this tool does not perform the requested "
        "action."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "description": (
                    "Short machine-readable category for "
                    "the requested action."
                ),
            },
            "title": {
                "type": "string",
                "description": (
                    "Short human-readable description of "
                    "the action requiring approval."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "Explain exactly what will happen if "
                    "the user approves the action."
                ),
            },
            "tool_name": {
                "type": "string",
                "description": (
                    "The tool that would be executed after "
                    "approval."
                ),
            },
            "tool_arguments_json": {
                "type": "string",
                "description": (
                    "JSON object encoded as a string "
                    "containing the arguments intended for "
                    "the approved tool call."
                ),
            },
        },
        "required": [
            "action_type",
            "title",
            "description",
            "tool_name",
            "tool_arguments_json",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}
LOAD_PROJECT_REPOSITORY_TOOL = {
    "type": "function",
    "name": "load_project_repository",
    "description": (
        "Load the GitHub repository linked to the current "
        "Projivo project into the isolated workspace. "
        "Use this before modifying an existing software project."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    "strict": True,
}
SYNC_PROJECT_REPOSITORY_TOOL = {
    "type": "function",
    "name": "sync_project_repository",
    "description": (
        "Commit changes from the loaded project repository "
        "workspace back to its linked GitHub repository. "
        "Only use this after load_project_repository. "
        "Creates one GitHub commit containing added, modified, "
        "and deleted files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commit_message": {
                "type": "string",
                "description": (
                    "Concise Git commit message describing "
                    "the changes."
                ),
            },
        },
        "required": [
            "commit_message",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}
AGENT_TOOLS = [
    {
        "type": "function",
        "name": "list_files",
        "description": (
            "List files and directories "
            "inside the isolated agent workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative directory path. "
                        "Use '.' for the workspace root."
                    ),
                },
            },
            "required": [
                "path",
            ],
            "additionalProperties": False,
        },
    },

    {
        "type": "function",
        "name": "read_file",
        "description": (
            "Read a text file from the "
            "isolated agent workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                },
            },
            "required": [
                "path",
            ],
            "additionalProperties": False,
        },
    },

    {
        "type": "function",
        "name": "write_file",
        "description": (
            "Create or overwrite a text file "
            "inside the isolated agent workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                },
                "content": {
                    "type": "string",
                },
            },
            "required": [
                "path",
                "content",
            ],
            "additionalProperties": False,
        },
    },

    {
        "type": "function",
        "name": "run_command",
        "description": (
            "Run a shell command inside a "
            "restricted Docker container "
            "mounted to the agent workspace."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Shell command to execute "
                        "inside the sandbox."
                    ),
                },
            },
            "required": [
                "command",
            ],
            "additionalProperties": False,
        },
    },
    LIST_CONNECTED_APPS_TOOL,
    CONNECTED_APP_TOOL,
    LOAD_PROJECT_REPOSITORY_TOOL,
    SYNC_PROJECT_REPOSITORY_TOOL,
    REQUEST_USER_APPROVAL_TOOL,
]

def load_project_repository(
    *,
    workspace,
    run,
):
    baseline_files = {}
    try:
        repository = (
            GitHubRepository.objects
            .get(project=run.project)
        )
    except GitHubRepository.DoesNotExist:
        raise ValueError(
            "This Projivo project does not have "
            "a linked GitHub repository."
        )

    github = get_user_integration(
        user=run.user,
        provider="github",
    )

    repo_path = (
        f"/repos/{repository.owner}/"
        f"{repository.name}"
    )

    repo_data = github.request(
        "GET",
        repo_path,
    )

    default_branch = (
        repo_data.get("default_branch")
        or repository.default_branch
        or "main"
    )

    # Record the exact commit that the agent
    # started working from.
    ref = github.request(
        "GET",
        (
            f"{repo_path}/git/ref/"
            f"heads/{default_branch}"
        ),
    )

    base_commit_sha = (
        ref["object"]["sha"]
    )

    if (
        repository.default_branch
        != default_branch
    ):
        repository.default_branch = (
            default_branch
        )

        repository.save(
            update_fields=[
                "default_branch",
                "updated_at",
            ]
        )

    
    workspace.record.repository_owner = (
        repository.owner
    )
    workspace.record.repository_name = (
        repository.name
    )
    workspace.record.repository_branch = (
        default_branch
    )
    workspace.record.base_commit_sha = (
        base_commit_sha
    )
    workspace.record.status = (
        AgentWorkspaceRecord.Status.ACTIVE
    )

    workspace.record.save(
        update_fields=[
            "repository_owner",
            "repository_name",
            "repository_branch",
            "base_commit_sha",
            "status",
            "updated_at",
        ]
    )

    
    tree = github.request(
        "GET",
        (
            f"{repo_path}/git/trees/"
            f"{default_branch}?recursive=1"
        ),
    )

    if tree.get("truncated"):
        raise ValueError(
            "GitHub repository tree is too large "
            "to load safely."
        )

    entries = tree.get("tree", [])

    blob_entries = [
        entry
        for entry in entries
        if entry.get("type") == "blob"
    ]

    max_files = 500
    max_file_bytes = 1_000_000
    max_total_bytes = 20_000_000

    if len(blob_entries) > max_files:
        raise ValueError(
            "Repository contains too many files "
            f"to load safely ({len(blob_entries)})."
        )

    total_bytes = 0
    loaded_files = []
    skipped_files = []

    repo_root = workspace._safe_path(
        repository.name
    )

    repo_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    for entry in blob_entries:
        relative_path = entry["path"]
        size = entry.get("size") or 0

        if size > max_file_bytes:
            skipped_files.append(
                {
                    "path": relative_path,
                    "reason": (
                        "File exceeds 1 MB "
                        "workspace loading limit."
                    ),
                }
            )
            continue

        if (
            total_bytes + size
            > max_total_bytes
        ):
            skipped_files.append(
                {
                    "path": relative_path,
                    "reason": (
                        "Repository exceeded "
                        "20 MB loading limit."
                    ),
                }
            )
            continue

        blob = github.request(
            "GET",
            (
                f"{repo_path}/git/blobs/"
                f"{entry['sha']}"
            ),
        )

        if blob.get("encoding") != "base64":
            skipped_files.append(
                {
                    "path": relative_path,
                    "reason": (
                        "Unsupported GitHub "
                        "blob encoding."
                    ),
                }
            )
            continue

        raw = base64.b64decode(
            blob["content"]
        )

        target = workspace._safe_path(
            f"{repository.name}/{relative_path}"
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_bytes(raw)

        total_bytes += len(raw)

        loaded_files.append(
            relative_path
        )
        baseline_files[relative_path] = {
            "sha256": hashlib.sha256(
                raw
            ).hexdigest(),
            "github_blob_sha": entry["sha"],
        }

    metadata = {
        "owner": repository.owner,
        "repository": repository.name,
        "default_branch": default_branch,
        "html_url": repository.html_url,
        "repository_id": repository.repository_id,
        "loaded_files": len(
            loaded_files
        ),
        "baseline_files": baseline_files,
        "base_commit_sha": base_commit_sha,
    }

    metadata_path = (
        workspace._safe_path(
            ".projivo/repository.json"
        )
    )

    metadata_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Give Astra normal local Git tooling,
    # without exposing GitHub credentials.
    result = workspace.run_command(
        (
            f"cd {repository.name!r} "
            "&& git init "
            f"--initial-branch={default_branch!r} "
            "&& git config "
            "user.name 'Projivo Agent' "
            "&& git config "
            "user.email "
            "'projivo-agent@users.noreply.github.com' "
            "&& git add . "
            "&& git commit "
            "-m 'chore: load repository baseline'"
        )
    )

    return {
        "repository": (
            f"{repository.owner}/"
            f"{repository.name}"
        ),
        "workspace_path": (
            repository.name
        ),
        "default_branch": (
            default_branch
        ),
        "files_loaded": len(
            loaded_files
        ),
        "bytes_loaded": (
            total_bytes
        ),
        "skipped_files": (
            skipped_files
        ),
        "git_initialization": {
            "returncode": (
                result["returncode"]
            ),
            "stderr": (
                result["stderr"]
            ),
        },
    }
def _file_sha256(path):
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def sync_project_repository(
    *,
    workspace,
    run,
    commit_message,
):
    metadata_path = workspace._safe_path(
        ".projivo/repository.json"
    )

    if not metadata_path.exists():
        raise ValueError(
            "No loaded project repository exists. "
            "Call load_project_repository first."
        )

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    owner = metadata["owner"]
    repository_name = metadata["repository"]
    default_branch = metadata["default_branch"]

    baseline_files = metadata.get(
        "baseline_files",
        {},
    )

    repository = (
        GitHubRepository.objects
        .get(project=run.project)
    )

    if (
        repository.owner != owner
        or repository.name != repository_name
    ):
        raise ValueError(
            "Workspace repository metadata does "
            "not match the linked Projivo repository."
        )

    github = get_user_integration(
        user=run.user,
        provider="github",
    )

    repo_root = workspace._safe_path(
        repository_name
    )

    if not repo_root.exists():
        raise ValueError(
            "Loaded repository workspace "
            "directory no longer exists."
        )

    current_files = {}

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(
            repo_root
        )

        # Never upload local Git internals.
        if ".git" in relative.parts:
            continue

        relative_path = (
            relative.as_posix()
        )

        data = path.read_bytes()

        current_files[
            relative_path
        ] = {
            "path": path,
            "sha256": hashlib.sha256(
                data
            ).hexdigest(),
            "size": len(data),
        }

    added = []
    modified = []
    deleted = []

    for path, info in current_files.items():
        previous = baseline_files.get(
            path
        )

        if previous is None:
            added.append(path)

        elif (
            previous.get("sha256")
            != info["sha256"]
        ):
            modified.append(path)

    for path in baseline_files:
        if path not in current_files:
            deleted.append(path)

    if not (
        added
        or modified
        or deleted
    ):
        return {
            "repository": (
                f"{owner}/{repository_name}"
            ),
            "changed": False,
            "added": [],
            "modified": [],
            "deleted": [],
            "message": (
                "No repository changes "
                "were detected."
            ),
        }

    if len(commit_message.strip()) < 3:
        raise ValueError(
            "Commit message is too short."
        )

    max_file_bytes = 1_000_000
    max_total_bytes = 20_000_000

    total_upload_bytes = 0

    for path in added + modified:
        size = current_files[
            path
        ]["size"]

        if size > max_file_bytes:
            raise ValueError(
                f"{path} exceeds the "
                "1 MB sync limit."
            )

        total_upload_bytes += size

    if total_upload_bytes > max_total_bytes:
        raise ValueError(
            "Repository changes exceed "
            "the 20 MB sync limit."
        )

    repo_path = (
        f"/repos/{owner}/"
        f"{repository_name}"
    )

    # Find current branch HEAD.
    ref = github.request(
        "GET",
        (
            f"{repo_path}/git/ref/"
            f"heads/{default_branch}"
        ),
    )

    parent_commit_sha = (
        ref["object"]["sha"]
    )
    expected_commit_sha = (
        metadata.get("base_commit_sha")
    )

    if not expected_commit_sha:
        raise ValueError(
            "Repository workspace is missing its "
            "base commit SHA. Reload the repository "
            "before syncing."
        )

    if (
        parent_commit_sha
        != expected_commit_sha
    ):
        raise ValueError(
            "The GitHub repository changed after "
            "this agent loaded it. Sync was blocked "
            "to avoid overwriting newer changes. "
            f"Expected {expected_commit_sha}, "
            f"but GitHub is now at "
            f"{parent_commit_sha}."
        )

    parent_commit = github.request(
        "GET",
        (
            f"{repo_path}/git/commits/"
            f"{parent_commit_sha}"
        ),
    )

    base_tree_sha = (
        parent_commit["tree"]["sha"]
    )

    tree_entries = []

    for relative_path in (
        added + modified
    ):
        raw = current_files[
            relative_path
        ]["path"].read_bytes()

        blob = github.request(
            "POST",
            f"{repo_path}/git/blobs",
            json={
                "content": base64.b64encode(
                    raw
                ).decode("ascii"),
                "encoding": "base64",
            },
        )

        tree_entries.append(
            {
                "path": relative_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            }
        )

    # sha=None removes a path from the new tree.
    for relative_path in deleted:
        tree_entries.append(
            {
                "path": relative_path,
                "mode": "100644",
                "type": "blob",
                "sha": None,
            }
        )

    new_tree = github.request(
        "POST",
        f"{repo_path}/git/trees",
        json={
            "base_tree": base_tree_sha,
            "tree": tree_entries,
        },
    )

    new_commit = github.request(
        "POST",
        f"{repo_path}/git/commits",
        json={
            "message": (
                commit_message.strip()
            ),
            "tree": new_tree["sha"],
            "parents": [
                parent_commit_sha
            ],
        },
    )

    github.request(
        "PATCH",
        (
            f"{repo_path}/git/refs/"
            f"heads/{default_branch}"
        ),
        json={
            "sha": new_commit["sha"],
            "force": False,
        },
    )

        # Update the GitHub baseline so calling sync
    # twice does not recommit the same changes.
    new_baseline = {}

    for path, info in current_files.items():
        new_baseline[path] = {
            "sha256": info["sha256"],
        }

    metadata["baseline_files"] = new_baseline

    # GitHub is now at the commit this agent created.
    metadata["base_commit_sha"] = new_commit["sha"]

    # Persist the new GitHub state in the DB.
    workspace.record.base_commit_sha = new_commit["sha"]
    workspace.record.last_synced_commit_sha = (
        new_commit["sha"]
    )

    workspace.record.save(
        update_fields=[
            "base_commit_sha",
            "last_synced_commit_sha",
            "updated_at",
        ]
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Advance the LOCAL Git baseline too.
    #
    # This commit is never pushed to GitHub. Its only
    # purpose is to make future `git diff` operations
    # represent work performed AFTER this successful
    # repository sync.
    #
    # Do this only after the GitHub update succeeded.
    local_baseline_result = workspace.run_command(
        command=(
            f"cd {shlex.quote(repository_name)} "
            "&& git add -A "
            "&& git commit "
            f"-m {shlex.quote('chore: update Projivo sync baseline')}"
        ),
    )

    local_baseline_updated = (
        local_baseline_result["returncode"] == 0
    )

    local_baseline_error = ""

    if not local_baseline_updated:
        local_baseline_error = (
            local_baseline_result.get("stderr", "")
            or local_baseline_result.get("stdout", "")
        )

    return {
        "repository": (
            f"{owner}/{repository_name}"
        ),
        "branch": default_branch,
        "changed": True,
        "commit_sha": new_commit["sha"],
        "commit_message": (
            commit_message.strip()
        ),
        "added": sorted(added),
        "modified": sorted(modified),
        "deleted": sorted(deleted),
        "local_baseline_updated": (
            local_baseline_updated
        ),
        "local_baseline_error": (
            local_baseline_error
        ),
    }
def finish_tool_execution(
    *,
    result,
    approval,
    run,
    tool_name,
):
    if approval is not None:
        consume_agent_tool_approval(
            approval=approval,
        )

    record_agent_tool_result(
        run=run,
        tool_name=tool_name,
        result=result,
    )

    return result
def get_agent_tool_activity_message(
    *,
    tool_name,
    arguments,
):
    if tool_name == "read_file":
        path = arguments.get(
            "path",
            "file",
        )

        return f"Reading {path}"

    if tool_name == "write_file":
        path = arguments.get(
            "path",
            "file",
        )

        return f"Updating {path}"

    if tool_name == "run_command":
        command = arguments.get(
            "command",
            "",
        )

        if len(command) > 80:
            command = (
                command[:77]
                + "..."
            )

        return (
            f"Running {command}"
            if command
            else "Running command"
        )

    if tool_name == "load_project_repository":
        return "Loading project repository"

    if tool_name == "sync_project_repository":
        return "Syncing changes to GitHub"

    if tool_name == "list_files":
        path = arguments.get(
            "path",
            ".",
        )

        return f"Inspecting {path}"

    if tool_name == "connected_app_request":
        provider = arguments.get(
            "provider",
            "connected app",
        )

        return (
            f"Using {provider.title()}"
        )

    if tool_name == "list_connected_apps":
        return "Checking connected apps"

    if tool_name == "request_user_approval":
        return "Requesting your approval"

    return (
        tool_name
        .replace("_", " ")
        .capitalize()
    )
def record_agent_tool_result(
    *,
    run,
    tool_name,
    result,
):
    message = None
    event_data = {}

    # -----------------------------------------
    # Repository loaded
    # -----------------------------------------

    if tool_name == "load_project_repository":
        repository = result.get(
            "repository",
            "repository",
        )

        message = (
            f"Loaded {repository}"
        )

        event_data.update({
            "repository": repository,
            "workspace_path": result.get(
                "workspace_path"
            ),
            "files_loaded": result.get(
                "files_loaded"
            ),
        })

    # -----------------------------------------
    # Repository synced
    # -----------------------------------------

    elif tool_name == "sync_project_repository":
        if result.get("changed"):
            message = (
                "Changes synced to GitHub"
            )
        else:
            message = (
                "Repository already up to date"
            )

        event_data.update({
            "repository": result.get(
                "repository"
            ),
            "branch": result.get(
                "branch"
            ),
            "changed": result.get(
                "changed",
                False,
            ),
            "commit_sha": result.get(
                "commit_sha"
            ),
            "added": result.get(
                "added",
                [],
            ),
            "modified": result.get(
                "modified",
                [],
            ),
            "deleted": result.get(
                "deleted",
                [],
            ),
        })

    # -----------------------------------------
    # File written
    # -----------------------------------------

    elif tool_name == "write_file":
        path = result.get(
            "path",
            "file",
        )

        message = (
            f"Updated {path}"
        )

        event_data.update({
            "path": path,
            "bytes": result.get(
                "bytes"
            ),
        })

    # -----------------------------------------
    # Command executed
    # -----------------------------------------

    elif tool_name == "run_command":
        returncode = result.get(
            "returncode"
        )

        if returncode == 0:
            message = "Command completed"
        else:
            message = (
                f"Command failed with "
                f"exit code {returncode}"
            )

        event_data.update({
            "returncode": returncode,
        })

    # -----------------------------------------
    # File read
    # -----------------------------------------

    elif tool_name == "read_file":
        message = "File read"

    # -----------------------------------------
    # Workspace inspected
    # -----------------------------------------

    elif tool_name == "list_files":
        message = "Workspace inspected"

    elif tool_name == "list_connected_apps":
        message = (
            "Connected apps checked"
        )

    elif tool_name == "connected_app_request":
        message = (
            "Connected app request completed"
        )

    if message is None:
        message = (
            tool_name
            .replace("_", " ")
            .capitalize()
            + " completed"
        )

    event_data["message"] = message

    AgentRunEvent.objects.create(
        run=run,
        event_type="tool_result",
        tool_name=tool_name,
        data=event_data,
    )

    return result
def finish_recoverable_tool_error(
    *,
    run,
    tool_name,
    error,
    message,
):
    result = {
        "ok": False,
        "error": error,
        "message": message,
        "recoverable": True,
    }

    AgentRunLog.objects.create(
        run=run,
        message=(
            f"{tool_name} could not complete: "
            f"{message}"
        ),
    )

    AgentRunEvent.objects.create(
        run=run,
        event_type="tool_error",
        tool_name=tool_name,
        data={
            "error": error,
            "message": message,
            "recoverable": True,
        },
    )

    return result
def execute_agent_tool(
    *,
    workspace,
    tool_name,
    arguments,
    run,
):
    AgentRunEvent.objects.create(
        run=run,
        event_type="tool_call",
        tool_name=tool_name,
        data={
            "message": get_agent_tool_activity_message(
                tool_name=tool_name,
                arguments=arguments,
            ),
        },
    )
    approval = None

    if tool_name != "request_user_approval":
        approval = get_agent_tool_approval(
            run=run,
            tool_name=tool_name,
            arguments=arguments,
        )
        try:
            continuation_approval = (
                run.continued_approval
            )
        except AgentApprovalRequest.DoesNotExist:
            continuation_approval = None

        if (
            continuation_approval is not None
            and continuation_approval.consumed_at is None
            and tool_name
            == continuation_approval.tool_name
        ):
            if approval is None:
                raise PermissionError(
                    "This tool call does not exactly match "
                    "the action approved by the user."
                )
        
    if tool_name == "request_user_approval":
        action_type = arguments[
            "action_type"
        ].strip()

        title = arguments[
            "title"
        ].strip()

        description = arguments[
            "description"
        ].strip()

        requested_tool_name = arguments[
            "tool_name"
        ].strip()

        try:
            tool_arguments = json.loads(
                arguments[
                    "tool_arguments_json"
                ]
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "tool_arguments_json must "
                "contain valid JSON."
            ) from exc

        if not isinstance(
            tool_arguments,
            dict,
        ):
            raise ValueError(
                "tool_arguments_json must "
                "decode to a JSON object."
            )

        approval = (
            AgentApprovalRequest.objects.create(
                run=run,
                action_type=action_type,
                title=title,
                description=description,
                tool_name=requested_tool_name,
                tool_arguments=tool_arguments,
            )
        )

        AgentRunLog.objects.create(
            run=run,
            message=(
                "User approval requested: "
                f"{title}"
            ),
        )
        

        return {
            "approval_required": True,
            "approval_id": approval.pk,
            "status": approval.status,
            "title": approval.title,
            "message": (
                "The requested action has not "
                "been executed. User approval "
                "is required before continuing."
            ),
        }
    if tool_name == "load_project_repository":
        result = load_project_repository(
            workspace=workspace,
            run=run,
        )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )


    if tool_name == "sync_project_repository":
        result = sync_project_repository(
            workspace=workspace,
            run=run,
            commit_message=(
                arguments["commit_message"]
            ),
        )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )


    if tool_name == "list_connected_apps":
        accounts = (
            ConnectedAccount.objects
            .filter(user=run.user)
            .values(
                "provider",
                "external_username",
            )
        )

        result = [
            {
                "provider": account["provider"],
                "username": (
                    account["external_username"]
                    or None
                ),
            }
            for account in accounts
        ]

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )


    if tool_name == "list_files":
        result = workspace.list_files(
            arguments.get(
                "path",
                ".",
            )
        )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )


    if tool_name == "read_file":
        result = workspace.read_file(
            arguments["path"]
        )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )


    if tool_name == "write_file":
        result = workspace.write_file(
            arguments["path"],
            arguments["content"],
        )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )


    if tool_name == "run_command":
        result = workspace.run_command(
            arguments["command"]
        )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )

    if tool_name == "connected_app_request":
        provider = arguments["provider"]

        method = (
            arguments["method"]
            .strip()
            .upper()
        )

        path = (
            arguments["path"]
            .strip()
        )

        body_json = (
            arguments["body_json"]
            .strip()
        )

        try:
            body = json.loads(
                body_json
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "body_json must contain valid JSON."
            ) from exc

        if not isinstance(body, dict):
            raise ValueError(
                "body_json must decode to a JSON object."
            )

        try:
            validate_connected_app_request(
                provider=provider,
                method=method,
                path=path,
            )

        except ConnectedAppPermissionError as exc:
            return finish_recoverable_tool_error(
                run=run,
                tool_name=tool_name,
                error="permission_denied",
                message=str(exc),
            )

        try:
            integration = get_user_integration(
                user=run.user,
                provider=provider,
            )

            result = integration.request(
                method,
                path,
                json=body,
            )

        except IntegrationError as exc:
            return finish_recoverable_tool_error(
                run=run,
                tool_name=tool_name,
                error="integration_error",
                message=str(exc),
            )

        except requests.Timeout:
            return finish_recoverable_tool_error(
                run=run,
                tool_name=tool_name,
                error="timeout",
                message=(
                    f"{provider.title()} did not respond "
                    "before the request timed out."
                ),
            )

        except requests.ConnectionError:
            return finish_recoverable_tool_error(
                run=run,
                tool_name=tool_name,
                error="connection_error",
                message=(
                    f"Could not connect to "
                    f"{provider.title()}."
                ),
            )

        except requests.RequestException as exc:
            return finish_recoverable_tool_error(
                run=run,
                tool_name=tool_name,
                error="request_error",
                message=(
                    f"{provider.title()} request failed: "
                    f"{exc}"
                ),
    )

        return finish_tool_execution(
            result=result,
            approval=approval,
            run=run,
            tool_name=tool_name,
        )
    raise ValueError(
        f"Unknown agent tool: {tool_name}"
    )
def get_agent_tool_approval(
    *,
    run,
    tool_name,
    arguments,
):
    """
    Find an unused approval for this exact tool call.

    This does NOT consume the approval.
    """

    approval = (
        AgentApprovalRequest.objects
        .filter(
            continuation_run=run,
            status=(
                AgentApprovalRequest
                .Status
                .APPROVED
            ),
            consumed_at__isnull=True,
            tool_name=tool_name,
        )
        .first()
    )

    if approval is None:
        return None

    if approval.tool_arguments != arguments:
        return None

    return approval


def consume_agent_tool_approval(
    *,
    approval,
):
    """
    Atomically consume an approval after the
    approved operation succeeds.
    """

    with transaction.atomic():
        locked_approval = (
            AgentApprovalRequest.objects
            .select_for_update()
            .get(pk=approval.pk)
        )

        if (
            locked_approval.status
            != AgentApprovalRequest.Status.APPROVED
        ):
            raise ValueError(
                "Approval is no longer approved."
            )

        if (
            locked_approval.consumed_at
            is not None
        ):
            raise ValueError(
                "Approval has already been consumed."
            )

        locked_approval.consumed_at = (
            timezone.now()
        )

        locked_approval.save(
            update_fields=[
                "consumed_at",
            ]
        )

        return locked_approval
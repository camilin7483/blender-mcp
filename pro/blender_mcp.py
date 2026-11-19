bl_info = {
    "name": "Blender MCP Pro Engine",
    "author": "Blender MCP Team & Senior Graphics Architecture",
    "version": (4, 0, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > MCP Pro",
    "description": "Universal High-Precision 3D Modeling Engine with BVHTree Intelligence, Organic Rigging, and Architectural Generators",
    "category": "Development",
}

import os
import os.path as osp
import sys
import re
import json
import time
import math
import hmac
import hashlib
import ipaddress
import secrets
import shutil
import socket
import select
import stat
import queue
import tempfile
import threading
import traceback
import urllib.request
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from contextlib import suppress

import bpy
import bmesh
from mathutils import Vector, Matrix, Euler, Quaternion
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

ADDON_PACKAGE = __name__.split(".")[0]

# ==============================================================================
# CONSTANTS & GLOBAL CONFIGURATION
# ==============================================================================
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876
BUFFER_SIZE = 65536
AUTH_TOKEN_ENV_VAR = "BLENDER_AUTH_TOKEN"
TOKEN_FILE_ENV_VAR = "BLENDER_MCP_TOKEN_FILE"
ALLOW_NO_AUTH_ENV_VAR = "BLENDER_MCP_ALLOW_NO_AUTH"
EXECUTE_CODE_ENV_VAR = "BLENDER_MCP_ALLOW_EXECUTE_CODE"
ALLOW_UNSAFE_OPS_ENV_VAR = "BLENDER_MCP_ALLOW_UNSAFE_OPS"
OUTPUT_DIR_ENV_VAR = "BLENDER_MCP_OUTPUT_DIR"
ALLOW_ANY_PATH_ENV_VAR = "BLENDER_MCP_ALLOW_ANY_PATH"
TOKEN_FILE_NAME = "token"

# Remote assets. Only provider domains are allowed, HTTPS only, with bounded
# downloads and safe ZIP extraction.
ALLOWED_DOWNLOAD_SUFFIXES = (".polyhaven.com", ".polyhaven.org", ".sketchfab.com")
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_ZIP_FILES = 10000
MAX_ZIP_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024

# Protocol limits. A single JSON message or response larger than these is
# rejected instead of growing an unbounded buffer.
MAX_MESSAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# Main-thread dispatcher. Socket threads enqueue work; a single persistent
# timer drains the queue on Blender's main thread.
MAIN_THREAD_TICK_SECONDS = 0.02
MAX_REQUESTS_PER_TICK = 8
MAX_CLIENTS = 5


@dataclass
class PendingRequest:
    """A socket request waiting for Blender's main thread."""

    cmd_type: str
    params: Dict[str, Any]
    request_id: Any
    response: Optional[Dict[str, Any]] = None
    done: threading.Event = field(default_factory=threading.Event)


def default_token_path() -> str:
    """Shared token path. Keep in sync with pro/mcp_server.py."""
    override = os.environ.get(TOKEN_FILE_ENV_VAR, "")
    if override:
        return os.path.expanduser(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "blender-mcp", TOKEN_FILE_NAME)


def load_or_create_auth_token() -> str:
    """Return the local auth token, creating a 0600 file on first start.

    Priority: explicit no-auth mode, BLENDER_AUTH_TOKEN, token file, new token.
    An empty return value means authentication is intentionally disabled.
    """
    if os.environ.get(ALLOW_NO_AUTH_ENV_VAR) == "1":
        return ""
    env_token = os.environ.get(AUTH_TOKEN_ENV_VAR, "")
    if env_token:
        return env_token

    path = default_token_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
        if token:
            with suppress(Exception):
                os.chmod(path, 0o600)
            return token
    except OSError:
        pass

    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    with suppress(Exception):
        os.chmod(directory, 0o700)

    token = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, "r", encoding="utf-8") as handle:
            existing = handle.read().strip()
        if existing:
            return existing
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    with suppress(Exception):
        os.chmod(path, 0o600)
    return token


def default_output_dir() -> str:
    return os.path.expanduser(os.environ.get(OUTPUT_DIR_ENV_VAR, "~/BlenderMCP/output"))


def resolve_output_path(filepath: str, allowed_extensions: set) -> str:
    """Resolve an export path inside the output sandbox.

    Relative paths are resolved against BLENDER_MCP_OUTPUT_DIR. Absolute
    paths must already be inside it. BLENDER_MCP_ALLOW_ANY_PATH=1 disables
    the sandbox for trusted automation; the extension is still validated.
    """
    if not str(filepath).strip():
        raise ValueError("filepath must not be empty")

    expanded = os.path.expanduser(str(filepath))
    base = default_output_dir()
    allow_any = os.environ.get(ALLOW_ANY_PATH_ENV_VAR) == "1"

    if allow_any or os.path.isabs(expanded):
        path = os.path.abspath(expanded)
    else:
        path = os.path.abspath(os.path.join(base, expanded))

    if not allow_any:
        base_real = os.path.normcase(os.path.realpath(base))
        path_real = os.path.normcase(os.path.realpath(path))
        try:
            inside = os.path.commonpath([base_real, path_real]) == base_real
        except ValueError:
            inside = False
        if not inside:
            raise PermissionError(
                f"Export path '{filepath}' is outside the output directory '{base}'. "
                f"Set {OUTPUT_DIR_ENV_VAR} or {ALLOW_ANY_PATH_ENV_VAR}=1 for trusted automation."
            )

    if not os.path.splitext(path)[1]:
        path += sorted(allowed_extensions)[0]
    extension = os.path.splitext(path)[1].lower()
    if extension not in allowed_extensions:
        raise ValueError(
            f"Unsupported extension '{extension}'. Expected one of {sorted(allowed_extensions)}."
        )
    return path


def sanitize_asset_id(value: str, label: str = "asset id") -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        raise ValueError(f"Invalid {label}: must be 1-128 characters")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    if safe in (".", ".."):
        raise ValueError(f"Invalid {label}: '{text}'")
    return safe


def _is_private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_download_url(url: str, resolve: bool = True) -> str:
    """Reject non-HTTPS, non-provider, credentialed and non-public URLs."""
    try:
        parsed = urllib.parse.urlparse(str(url))
        port = parsed.port
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise ValueError(f"Invalid download URL: {exc}") from exc

    if parsed.scheme != "https":
        raise ValueError("Only HTTPS downloads are allowed")
    if not host:
        raise ValueError("Download URL has no host")
    allowed = any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in ALLOWED_DOWNLOAD_SUFFIXES
    )
    if not allowed:
        raise ValueError(f"Download host '{host}' is not allowed")
    if parsed.username or parsed.password:
        raise ValueError("Download URL must not contain credentials")

    if resolve:
        try:
            infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"Cannot resolve download host '{host}': {exc}") from exc
        for info in infos:
            if _is_private_ip(info[4][0]):
                raise ValueError(f"Download host '{host}' resolves to a non-public address")
    return str(url)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_url(
    url: str,
    timeout: float,
    max_bytes: int,
    headers: Optional[Dict[str, str]] = None,
):
    validate_download_url(url)
    request_headers = {"User-Agent": "BlenderMCP-Pro/3.0"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    response = opener.open(request, timeout=timeout)
    length = response.headers.get("Content-Length")
    if length:
        try:
            too_large = int(length) > max_bytes
        except ValueError:
            response.close()
            raise ValueError(f"Invalid Content-Length header: {length!r}")
        if too_large:
            response.close()
            raise ValueError(f"Response exceeds maximum size ({max_bytes} bytes)")
    return response


def fetch_json(url: str, timeout: float = 20.0, headers: Optional[Dict[str, str]] = None) -> Any:
    with _open_url(url, timeout, MAX_API_RESPONSE_BYTES, headers) as response:
        data = response.read(MAX_API_RESPONSE_BYTES + 1)
    if len(data) > MAX_API_RESPONSE_BYTES:
        raise ValueError(f"API response exceeds maximum size ({MAX_API_RESPONSE_BYTES} bytes)")
    return json.loads(data.decode("utf-8"))


def download_to_file(
    url: str,
    destination: str,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = 180.0,
) -> str:
    try:
        with _open_url(url, timeout, max_bytes) as response, open(destination, "wb") as handle:
            total = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Download exceeds maximum size ({max_bytes} bytes)")
                handle.write(chunk)
    except Exception:
        with suppress(Exception):
            os.unlink(destination)
        raise
    return destination


def safe_extract_zip(
    zip_path: str,
    destination: str,
    max_files: int = MAX_ZIP_FILES,
    max_bytes: int = MAX_ZIP_UNCOMPRESSED_BYTES,
) -> None:
    """Extract a ZIP without path traversal, symlinks, bombs or encrypted entries."""
    dest_real = os.path.realpath(destination)
    os.makedirs(dest_real, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > max_files:
            raise ValueError(f"ZIP contains too many files ({len(infos)} > {max_files})")

        total = 0
        for info in infos:
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if info.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP entries are not allowed")

            normalized = os.path.normpath(name)
            if os.path.isabs(normalized) or normalized == ".." or normalized.startswith(".." + os.sep):
                raise ValueError(f"ZIP entry escapes the destination: {info.filename}")

            raw_target = os.path.join(dest_real, normalized)
            if os.path.islink(raw_target):
                raise ValueError(f"ZIP entry targets a symlink: {info.filename}")
            target = os.path.realpath(raw_target)
            if os.path.commonpath([os.path.normcase(dest_real), os.path.normcase(target)]) != os.path.normcase(dest_real):
                raise ValueError(f"ZIP entry escapes the destination: {info.filename}")

            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ValueError(f"ZIP entry is a symlink: {info.filename}")

            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info, "r") as source, open(target, "wb") as output:
                while True:
                    chunk = source.read(1024 * 256)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(
                            f"ZIP expands beyond the maximum size ({max_bytes} bytes)"
                        )
                    output.write(chunk)


@dataclass
class Tolerance:
    """Absolute, relative and maximum allowed error."""

    absolute: float = 0.001
    relative: float = 0.0
    max_error: Optional[float] = None

    def allowed(self, expected: float) -> float:
        value = max(float(self.absolute), abs(float(expected)) * float(self.relative))
        if self.max_error is not None:
            value = min(value, float(self.max_error))
        return value

    def within(self, actual: float, expected: float) -> bool:
        return abs(float(actual) - float(expected)) <= self.allowed(expected)


@dataclass
class GeometrySnapshot:
    """Evaluated mesh data in local and world space."""

    name: str
    unit_scale: float
    world_aabb: List[List[float]]
    local_aabb: List[List[float]]
    vertices_world: List[Vector]
    face_centers_world: List[Vector]
    face_areas: List[float]
    face_count: int
    bvh: BVHTree


class GeometryService:
    """Evaluated-geometry measurements. AABB is broad-phase only."""

    @classmethod
    def snapshot(cls, obj: bpy.types.Object) -> GeometrySnapshot:
        if obj.type != "MESH":
            raise TypeError(f"Object '{obj.name}' must be a MESH (got {obj.type})")

        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            if mesh is None or len(mesh.vertices) == 0:
                raise ValueError(f"Object '{obj.name}' has no evaluated vertices")

            matrix = eval_obj.matrix_world.copy()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            local_vertices = [v.co.copy() for v in bm.verts]
            bm.transform(matrix)
            vertices = [v.co.copy() for v in bm.verts]
            face_centers = [f.calc_center_median() for f in bm.faces]
            face_areas = [f.calc_area() for f in bm.faces]
            face_count = len(bm.faces)
            bvh = BVHTree.FromBMesh(bm, epsilon=1e-6)
            bm.free()

            world_min = Vector((
                min(v.x for v in vertices),
                min(v.y for v in vertices),
                min(v.z for v in vertices),
            ))
            world_max = Vector((
                max(v.x for v in vertices),
                max(v.y for v in vertices),
                max(v.z for v in vertices),
            ))
            local_min = Vector((
                min(v.x for v in local_vertices),
                min(v.y for v in local_vertices),
                min(v.z for v in local_vertices),
            ))
            local_max = Vector((
                max(v.x for v in local_vertices),
                max(v.y for v in local_vertices),
                max(v.z for v in local_vertices),
            ))
            unit_scale = float(bpy.context.scene.unit_settings.scale_length or 1.0)
            return GeometrySnapshot(
                name=obj.name,
                unit_scale=unit_scale,
                world_aabb=[[round(float(c), 6) for c in world_min], [round(float(c), 6) for c in world_max]],
                local_aabb=[[round(float(c), 6) for c in local_min], [round(float(c), 6) for c in local_max]],
                vertices_world=vertices,
                face_centers_world=face_centers,
                face_areas=face_areas,
                face_count=face_count,
                bvh=bvh,
            )
        finally:
            eval_obj.to_mesh_clear()

    @staticmethod
    def aabb_gap(a: GeometrySnapshot, b: GeometrySnapshot) -> float:
        gap_sq = 0.0
        for axis in range(3):
            a_min, a_max = a.world_aabb[0][axis], a.world_aabb[1][axis]
            b_min, b_max = b.world_aabb[0][axis], b.world_aabb[1][axis]
            if a_max < b_min:
                gap_sq += (b_min - a_max) ** 2
            elif b_max < a_min:
                gap_sq += (a_min - b_max) ** 2
        return math.sqrt(gap_sq)

    @classmethod
    def nearest_distance(
        cls,
        a: GeometrySnapshot,
        b: GeometrySnapshot,
        max_samples: int = 20000,
    ) -> Tuple[float, bool, str, int]:
        """Return (distance, approximate, method, overlap_pairs)."""
        pairs = a.bvh.overlap(b.bvh)
        if pairs:
            return 0.0, False, "bvh_overlap", len(pairs)

        points_a = a.vertices_world + a.face_centers_world
        points_b = b.vertices_world + b.face_centers_world
        approximate = len(points_a) > max_samples or len(points_b) > max_samples
        best = float("inf")

        for points, tree in ((points_a, b.bvh), (points_b, a.bvh)):
            step = max(1, math.ceil(len(points) / max_samples))
            for point in points[::step]:
                location, _normal, _index, distance = tree.find_nearest(point)
                if location is not None and distance < best:
                    best = distance

        if best == float("inf"):
            return cls.aabb_gap(a, b), True, "bvh_nearest_failed", 0
        return float(best), approximate, "bvh_nearest", 0

    @classmethod
    def contact_graph(
        cls,
        objects: List[bpy.types.Object],
        tolerance: float = 0.001,
    ) -> Dict[str, Any]:
        snapshots = [cls.snapshot(obj) for obj in objects]
        pairs_out: List[Dict[str, Any]] = []
        threshold = max(float(tolerance), 0.6)

        for i in range(len(snapshots)):
            for j in range(i + 1, len(snapshots)):
                a, b = snapshots[i], snapshots[j]
                gap = cls.aabb_gap(a, b)
                if gap > threshold:
                    pairs_out.append({
                        "a": a.name,
                        "b": b.name,
                        "min_distance": round(gap, 6),
                        "contact": False,
                        "surface_intersection": False,
                        "overlap_face_pairs": 0,
                        "estimated_contact_area": None,
                        "method": "aabb_broad_phase",
                        "confidence": 0.5,
                        "approximate": True,
                    })
                    continue

                overlap_pairs = a.bvh.overlap(b.bvh)
                if overlap_pairs:
                    area_a = sum(
                        a.face_areas[index]
                        for index in {pair[0] for pair in overlap_pairs}
                        if index < len(a.face_areas)
                    )
                    area_b = sum(
                        b.face_areas[index]
                        for index in {pair[1] for pair in overlap_pairs}
                        if index < len(b.face_areas)
                    )
                    pairs_out.append({
                        "a": a.name,
                        "b": b.name,
                        "min_distance": 0.0,
                        "contact": True,
                        "surface_intersection": True,
                        "overlap_face_pairs": len(overlap_pairs),
                        "estimated_contact_area": round(min(area_a, area_b), 6),
                        "method": "bvh_overlap",
                        "confidence": 1.0,
                        "approximate": False,
                    })
                    continue

                distance, approximate, method, _ = cls.nearest_distance(a, b)
                pairs_out.append({
                    "a": a.name,
                    "b": b.name,
                    "min_distance": round(distance, 6),
                    "contact": distance <= tolerance,
                    "surface_intersection": False,
                    "overlap_face_pairs": 0,
                    "estimated_contact_area": None,
                    "method": method,
                    "confidence": 0.8 if not approximate else 0.6,
                    "approximate": approximate,
                })

        return {
            "tolerance": float(tolerance),
            "objects": [snapshot.name for snapshot in snapshots],
            "pairs": pairs_out,
        }

    @classmethod
    def topology_metrics(
        cls,
        obj: bpy.types.Object,
        merge_distance: float = 1e-6,
        area_epsilon: float = 1e-9,
        check_self_intersections: bool = False,
    ) -> Dict[str, Any]:
        if obj.type != "MESH":
            raise TypeError(f"Object '{obj.name}' must be a MESH (got {obj.type})")

        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        bm = bmesh.new()
        try:
            bm.from_object(eval_obj, depsgraph)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            if len(bm.verts) == 0:
                raise ValueError(f"Object '{obj.name}' has no evaluated vertices")

            non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
            boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
            loose_edges = sum(1 for edge in bm.edges if len(edge.link_faces) == 0)
            loose_vertices = sum(1 for vert in bm.verts if len(vert.link_edges) == 0)
            zero_area = sum(1 for face in bm.faces if face.calc_area() < area_epsilon)
            degenerate = sum(
                1 for face in bm.faces if len({vert.index for vert in face.verts}) < 3
            )

            duplicate_vertices = 0
            buckets: set = set()
            step = max(float(merge_distance), 1e-9)
            for vert in bm.verts:
                key = (
                    round(vert.co.x / step),
                    round(vert.co.y / step),
                    round(vert.co.z / step),
                )
                if key in buckets:
                    duplicate_vertices += 1
                else:
                    buckets.add(key)

            remaining = set(bm.verts)
            components = 0
            while remaining:
                components += 1
                stack = [remaining.pop()]
                while stack:
                    current = stack.pop()
                    for edge in current.link_edges:
                        other = edge.other_vert(current)
                        if other in remaining:
                            remaining.remove(other)
                            stack.append(other)

            before = [face.normal.copy() for face in bm.faces]
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            inverted_normals = sum(
                1 for face, old_normal in zip(bm.faces, before) if face.normal.dot(old_normal) < 0
            )

            self_intersections: Optional[int] = None
            if check_self_intersections and 0 < len(bm.faces) <= 20000:
                bvh = BVHTree.FromBMesh(bm, epsilon=1e-6)
                unique_pairs = set()
                for first, second in bvh.overlap(bvh):
                    if first == second:
                        continue
                    face_a, face_b = bm.faces[first], bm.faces[second]
                    if {vert.index for vert in face_a.verts} & {vert.index for vert in face_b.verts}:
                        continue
                    unique_pairs.add((min(first, second), max(first, second)))
                self_intersections = len(unique_pairs)

            return {
                "object": obj.name,
                "vertex_count": len(bm.verts),
                "edge_count": len(bm.edges),
                "face_count": len(bm.faces),
                "non_manifold_edges": non_manifold,
                "boundary_edges": boundary,
                "loose_edges": loose_edges,
                "loose_vertices": loose_vertices,
                "zero_area_faces": zero_area,
                "degenerate_faces": degenerate,
                "duplicate_vertices": duplicate_vertices,
                "inverted_normals": inverted_normals,
                "disconnected_components": components,
                "self_intersections": self_intersections,
                "merge_distance": float(merge_distance),
                "area_epsilon": float(area_epsilon),
                "method": "bmesh_evaluated",
            }
        finally:
            bm.free()

    @classmethod
    def symmetry_error(
        cls,
        objects: List[bpy.types.Object],
        axis: str = "X",
        plane: float = 0.0,
        tolerance: float = 0.001,
    ) -> Dict[str, Any]:
        axis_index = {"X": 0, "Y": 1, "Z": 2}.get(str(axis).upper())
        if axis_index is None:
            raise ValueError(f"Invalid symmetry axis '{axis}'. Use X, Y or Z.")

        vertices: List[Vector] = []
        for obj in objects:
            vertices.extend(cls.snapshot(obj).vertices_world)
        if not vertices:
            raise ValueError("No evaluated vertices for symmetry measurement")

        tree = KDTree(len(vertices))
        for index, vertex in enumerate(vertices):
            tree.insert(vertex, index)
        tree.balance()

        errors: List[float] = []
        for vertex in vertices:
            mirrored = vertex.copy()
            mirrored[axis_index] = 2.0 * float(plane) - mirrored[axis_index]
            _location, _index, distance = tree.find(mirrored)
            if distance is not None:
                errors.append(float(distance))

        max_error = max(errors) if errors else float("inf")
        mean_error = sum(errors) / len(errors) if errors else float("inf")
        return {
            "axis": str(axis).upper(),
            "plane": float(plane),
            "tolerance": float(tolerance),
            "max_error": round(max_error, 6),
            "mean_error": round(mean_error, 6),
            "passed": max_error <= tolerance,
            "method": "kdtree_vertex_symmetry",
            "confidence": 0.6,
            "vertex_count": len(vertices),
        }

    @staticmethod
    def ground_contact(
        snapshots: List[GeometrySnapshot],
        tolerance: float = 0.005,
    ) -> Dict[str, Any]:
        if not snapshots:
            return {
                "passed": True,
                "min_z": None,
                "tolerance": float(tolerance),
                "method": "evaluated_world_aabb",
            }
        min_z = min(snapshot.world_aabb[0][2] for snapshot in snapshots)
        return {
            "passed": abs(min_z) <= tolerance,
            "min_z": round(float(min_z), 6),
            "tolerance": float(tolerance),
            "method": "evaluated_world_aabb",
        }


@dataclass
class SemanticAnchor:
    """Named point with a world position, normal, tangent and local frame."""

    name: str
    anchor_type: str
    object_name: str
    position: List[float]
    normal: List[float]
    tangent: List[float]
    local_frame: List[List[float]]
    space: str
    source: str
    confidence: float
    tolerance: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.anchor_type,
            "object": self.object_name,
            "position": self.position,
            "normal": self.normal,
            "tangent": self.tangent,
            "local_frame": self.local_frame,
            "space": self.space,
            "source": self.source,
            "confidence": self.confidence,
            "tolerance": self.tolerance,
        }


class AnchorService:
    """Semantic anchors derived from evaluated geometry and object data."""

    @classmethod
    def _make(
        cls,
        obj: bpy.types.Object,
        name: str,
        anchor_type: str,
        position: Any,
        normal: Any,
        tangent: Any,
        source: str,
        confidence: float,
        tolerance: float = 0.001,
    ) -> SemanticAnchor:
        point = Vector(position)
        direction = Vector(normal)
        tangent_vector = Vector(tangent)
        if direction.length < 1e-9:
            direction = Vector((0.0, 0.0, 1.0))
        direction.normalize()
        tangent_vector = tangent_vector - direction * tangent_vector.dot(direction)
        if tangent_vector.length < 1e-9:
            tangent_vector = direction.orthogonal()
        tangent_vector.normalize()
        bitangent = direction.cross(tangent_vector).normalized()
        frame = [
            [round(float(value), 6) for value in tangent_vector],
            [round(float(value), 6) for value in bitangent],
            [round(float(value), 6) for value in direction],
        ]
        return SemanticAnchor(
            name=name,
            anchor_type=anchor_type,
            object_name=obj.name,
            position=[round(float(value), 6) for value in point],
            normal=[round(float(value), 6) for value in direction],
            tangent=[round(float(value), 6) for value in tangent_vector],
            local_frame=frame,
            space="world",
            source=source,
            confidence=float(confidence),
            tolerance=float(tolerance),
        )

    @classmethod
    def for_object(cls, obj: bpy.types.Object) -> Dict[str, SemanticAnchor]:
        anchors: Dict[str, SemanticAnchor] = {}

        if obj.type == "ARMATURE":
            for bone in obj.data.bones:
                head = obj.matrix_world @ bone.head_local
                tail = obj.matrix_world @ bone.tail_local
                direction = tail - head
                if direction.length < 1e-9:
                    continue
                direction.normalize()
                tangent = direction.orthogonal()
                for suffix, position in (("HEAD", head), ("TAIL", tail)):
                    name = f"BONE_{bone.name.upper()}_{suffix}"
                    anchors[name] = cls._make(
                        obj, name, "bone", position, direction, tangent,
                        "armature_bone", 1.0,
                    )
            return anchors

        if obj.type != "MESH":
            raise TypeError(
                f"Anchors need a MESH or ARMATURE object (got '{obj.type}')"
            )

        snapshot = GeometryService.snapshot(obj)
        bmin = Vector(snapshot.world_aabb[0])
        bmax = Vector(snapshot.world_aabb[1])
        center = (bmin + bmax) / 2.0
        extent = bmax - bmin
        max_extent = max(extent.x, extent.y, extent.z, 0.001)

        anchors["CENTER"] = cls._make(
            obj, "CENTER", "center", center, (0, 0, 1), (1, 0, 0),
            "evaluated_aabb", 0.8,
        )
        anchors["INSIDE_CENTER"] = cls._make(
            obj, "INSIDE_CENTER", "center", center, (0, 0, 1), (1, 0, 0),
            "evaluated_aabb", 0.8,
        )

        faces = {
            "+X": ((bmax.x, center.y, center.z), (1, 0, 0), (0, 1, 0)),
            "-X": ((bmin.x, center.y, center.z), (-1, 0, 0), (0, 1, 0)),
            "+Y": ((center.x, bmax.y, center.z), (0, 1, 0), (1, 0, 0)),
            "-Y": ((center.x, bmin.y, center.z), (0, -1, 0), (1, 0, 0)),
            "+Z": ((center.x, center.y, bmax.z), (0, 0, 1), (1, 0, 0)),
            "-Z": ((center.x, center.y, bmin.z), (0, 0, -1), (1, 0, 0)),
        }
        face_aliases = {
            "TOP_CENTER": "+Z",
            "BOTTOM_CENTER": "-Z",
            "RIGHT_CENTER": "+X",
            "LEFT_CENTER": "-X",
            "BACK_CENTER": "+Y",
            "FRONT_CENTER": "-Y",
        }
        for label, (position, normal, tangent) in faces.items():
            anchors[f"FACE_{label}"] = cls._make(
                obj, f"FACE_{label}", "face_center", position, normal, tangent,
                "evaluated_aabb", 0.8,
            )
            origin = Vector(position) + Vector(normal) * (max_extent + 0.5)
            hit, hit_normal, _index, _distance = snapshot.bvh.ray_cast(
                origin, -Vector(normal)
            )
            if hit is not None:
                anchors[f"SURFACE_{label}"] = cls._make(
                    obj, f"SURFACE_{label}", "surface", hit, hit_normal, tangent,
                    "bvh_raycast", 0.95,
                )
            else:
                anchors[f"SURFACE_{label}"] = cls._make(
                    obj, f"SURFACE_{label}", "surface", position, normal, tangent,
                    "evaluated_aabb_fallback", 0.5,
                )
        for alias, label in face_aliases.items():
            anchors[alias] = anchors[f"FACE_{label}"]

        for edge_axis, edge_index in (("X", 0), ("Y", 1), ("Z", 2)):
            other_axes = [index for index in range(3) if index != edge_index]
            for first_side in (0, 1):
                for second_side in (0, 1):
                    position = center.copy()
                    normal = Vector((0.0, 0.0, 0.0))
                    tangent = Vector((0.0, 0.0, 0.0))
                    tangent[edge_index] = 1.0
                    name_parts = ["EDGE"]
                    for axis_index, side in (
                        (other_axes[0], first_side),
                        (other_axes[1], second_side),
                    ):
                        axis_name = "XYZ"[axis_index]
                        position[axis_index] = (
                            bmin[axis_index] if side == 0 else bmax[axis_index]
                        )
                        normal[axis_index] = -1.0 if side == 0 else 1.0
                        name_parts.append(f"{axis_name}{side}")
                    name = f"EDGE_{name_parts[1]}{name_parts[2]}"
                    anchors[name] = cls._make(
                        obj, name, "edge_mid", position, normal, tangent,
                        "evaluated_aabb", 0.75,
                    )

        corner_aliases = {
            "CORNER_FL": "CORNER_X0Y0Z1",
            "CORNER_FR": "CORNER_X1Y0Z1",
            "CORNER_BL": "CORNER_X0Y1Z1",
            "CORNER_BR": "CORNER_X1Y1Z1",
        }
        for x_side in (0, 1):
            for y_side in (0, 1):
                for z_side in (0, 1):
                    position = Vector((
                        bmin.x if x_side == 0 else bmax.x,
                        bmin.y if y_side == 0 else bmax.y,
                        bmin.z if z_side == 0 else bmax.z,
                    ))
                    normal = Vector((
                        -1.0 if x_side == 0 else 1.0,
                        -1.0 if y_side == 0 else 1.0,
                        -1.0 if z_side == 0 else 1.0,
                    ))
                    tangent = Vector((1, 0, 0)) if abs(normal.x) < 0.9 else Vector((0, 1, 0))
                    name = f"CORNER_X{x_side}Y{y_side}Z{z_side}"
                    anchors[name] = cls._make(
                        obj, name, "corner", position, normal, tangent,
                        "evaluated_aabb", 0.75,
                    )
        for alias, target in corner_aliases.items():
            anchors[alias] = anchors[target]
        anchors["TOP_FRONT_EDGE"] = anchors["EDGE_Y0Z1"]
        anchors["TOP_BACK_EDGE"] = anchors["EDGE_Y1Z1"]

        for other in bpy.context.scene.objects:
            if other.type != "EMPTY":
                continue
            if other.parent is not obj and not other.name.startswith(f"{obj.name}_socket_"):
                continue
            if "socket_" in other.name:
                socket_name = other.name.split("socket_")[-1].upper()
            else:
                socket_name = other.name.upper()
            position = other.matrix_world.translation.copy()
            rotation = other.matrix_world.to_3x3()
            normal = (rotation @ Vector((0, 0, 1))).normalized()
            tangent = (rotation @ Vector((1, 0, 0))).normalized()
            name = f"SOCKET_{socket_name}"
            anchors[name] = cls._make(
                obj, name, "socket", position, normal, tangent,
                "empty_object", 0.9,
            )

        custom = obj.get("mcp_anchors")
        if isinstance(custom, dict):
            for custom_name, data in custom.items():
                if not isinstance(data, dict):
                    continue
                name = f"CUSTOM_{str(custom_name).upper()}"
                anchors[name] = cls._make(
                    obj,
                    name,
                    "custom",
                    data.get("position", center),
                    data.get("normal", (0, 0, 1)),
                    data.get("tangent", (1, 0, 0)),
                    "custom_property",
                    float(data.get("confidence", 0.9)),
                    float(data.get("tolerance", 0.001)),
                )

        return anchors

    @classmethod
    def get(cls, obj: bpy.types.Object, name: str) -> SemanticAnchor:
        anchors = cls.for_object(obj)
        key = str(name).strip().upper()
        if key not in anchors:
            available = ", ".join(sorted(anchors)[:12])
            raise ValueError(
                f"Unknown anchor '{name}' on '{obj.name}'. Available: {available}..."
            )
        return anchors[key]

    @classmethod
    def align(
        cls,
        part: bpy.types.Object,
        target: bpy.types.Object,
        part_anchor: str,
        target_anchor: str,
        offset: Optional[List[float]] = None,
        parent_to_target: bool = False,
    ) -> Dict[str, Any]:
        source = cls.get(part, part_anchor)
        destination = cls.get(target, target_anchor)
        offset_vector = Vector(offset or (0.0, 0.0, 0.0))
        delta = Vector(destination.position) - Vector(source.position) + offset_vector
        part.matrix_world = Matrix.Translation(delta) @ part.matrix_world
        bpy.context.view_layer.update()
        if parent_to_target:
            part.parent = target
            part.matrix_parent_inverse = target.matrix_world.inverted()
            bpy.context.view_layer.update()
        after = cls.get(part, part_anchor)
        desired = Vector(destination.position) + offset_vector
        distance = (Vector(after.position) - desired).length
        return {
            "success": True,
            "operation": "align",
            "part": part.name,
            "target": target.name,
            "part_anchor": after.to_dict(),
            "target_anchor": destination.to_dict(),
            "delta": [round(float(value), 6) for value in delta],
            "distance": round(float(distance), 6),
            "passed": distance <= after.tolerance,
        }

    @classmethod
    def mate(
        cls,
        part: bpy.types.Object,
        target: bpy.types.Object,
        part_anchor: str,
        target_anchor: str,
        gap: float = 0.0,
        parent_to_target: bool = False,
    ) -> Dict[str, Any]:
        source = cls.get(part, part_anchor)
        destination = cls.get(target, target_anchor)
        part_normal = Vector(source.normal).normalized()
        target_normal = Vector(destination.normal).normalized()
        rotation = part_normal.rotation_difference(-target_normal)
        pivot = Vector(source.position)
        part.matrix_world = (
            Matrix.Translation(pivot)
            @ rotation.to_matrix().to_4x4()
            @ Matrix.Translation(-pivot)
            @ part.matrix_world
        )
        bpy.context.view_layer.update()
        rotated_normal = (rotation @ part_normal).normalized()
        after = cls.get(part, part_anchor)
        desired = Vector(destination.position) + target_normal * float(gap)
        delta = desired - Vector(after.position)
        part.matrix_world = Matrix.Translation(delta) @ part.matrix_world
        bpy.context.view_layer.update()
        if parent_to_target:
            part.parent = target
            part.matrix_parent_inverse = target.matrix_world.inverted()
            bpy.context.view_layer.update()
        after = cls.get(part, part_anchor)
        distance = (Vector(after.position) - desired).length
        normal_dot = rotated_normal.dot(-target_normal)
        return {
            "success": True,
            "operation": "mate",
            "part": part.name,
            "target": target.name,
            "part_anchor": after.to_dict(),
            "target_anchor": destination.to_dict(),
            "gap": float(gap),
            "distance": round(float(distance), 6),
            "normal_dot": round(float(normal_dot), 6),
            "passed": distance <= after.tolerance and normal_dot >= 0.999,
        }

    @classmethod
    def offset(
        cls,
        part: bpy.types.Object,
        part_anchor: str,
        offset: List[float],
    ) -> Dict[str, Any]:
        anchor = cls.get(part, part_anchor)
        delta = Vector(offset)
        part.matrix_world = Matrix.Translation(delta) @ part.matrix_world
        bpy.context.view_layer.update()
        after = cls.get(part, part_anchor)
        return {
            "success": True,
            "operation": "offset",
            "part": part.name,
            "part_anchor": after.to_dict(),
            "delta": [round(float(value), 6) for value in delta],
            "passed": True,
        }

    @classmethod
    def orient_normal(
        cls,
        part: bpy.types.Object,
        part_anchor: str,
        normal: List[float],
    ) -> Dict[str, Any]:
        anchor = cls.get(part, part_anchor)
        desired = Vector(normal)
        if desired.length < 1e-9:
            raise ValueError("orient_normal needs a non-zero normal")
        desired.normalize()
        current = (part.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        rotation = current.rotation_difference(desired)
        pivot = Vector(anchor.position)
        part.matrix_world = (
            Matrix.Translation(pivot)
            @ rotation.to_matrix().to_4x4()
            @ Matrix.Translation(-pivot)
            @ part.matrix_world
        )
        bpy.context.view_layer.update()
        after = (part.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        dot = after.dot(desired)
        return {
            "success": True,
            "operation": "orient_normal",
            "part": part.name,
            "part_anchor": cls.get(part, part_anchor).to_dict(),
            "normal": [round(float(value), 6) for value in desired],
            "dot": round(float(dot), 6),
            "passed": dot >= 0.999,
        }

    @classmethod
    def distribute(
        cls,
        objects: List[bpy.types.Object],
        axis: str = "X",
        spacing: Optional[float] = None,
    ) -> Dict[str, Any]:
        if len(objects) < 2:
            raise ValueError("distribute needs at least two objects")
        axis_index = {"X": 0, "Y": 1, "Z": 2}.get(str(axis).upper())
        if axis_index is None:
            raise ValueError(f"Invalid axis '{axis}'. Use X, Y or Z.")
        ordered = sorted(
            objects,
            key=lambda item: (item.matrix_world.translation[axis_index], item.name),
        )
        if spacing is None:
            gaps = [
                ordered[index + 1].matrix_world.translation[axis_index]
                - ordered[index].matrix_world.translation[axis_index]
                for index in range(len(ordered) - 1)
            ]
            step = sum(gaps) / len(gaps) if gaps else 0.1
            if abs(step) < 1e-6:
                step = 0.1
        else:
            step = float(spacing)
        start = ordered[0].matrix_world.translation[axis_index]
        final_positions = []
        for index, item in enumerate(ordered):
            matrix = item.matrix_world.copy()
            matrix.translation[axis_index] = start + index * step
            item.matrix_world = matrix
            final_positions.append({
                "object": item.name,
                "position": [round(float(value), 6) for value in matrix.translation],
            })
        bpy.context.view_layer.update()
        return {
            "success": True,
            "operation": "distribute",
            "axis": str(axis).upper(),
            "spacing": round(float(step), 6),
            "objects": final_positions,
            "passed": True,
        }

    @classmethod
    def mirror(
        cls,
        objects: List[bpy.types.Object],
        axis: str = "X",
        plane: float = 0.0,
        duplicate: bool = True,
    ) -> Dict[str, Any]:
        if not objects:
            raise ValueError("mirror needs at least one object")
        axis_index = {"X": 0, "Y": 1, "Z": 2}.get(str(axis).upper())
        if axis_index is None:
            raise ValueError(f"Invalid axis '{axis}'. Use X, Y or Z.")
        matrix = Matrix.Identity(4)
        matrix[axis_index][axis_index] = -1.0
        matrix.translation[axis_index] = 2.0 * float(plane)
        created = []
        for item in objects:
            if duplicate:
                copy = item.copy()
                if item.data is not None:
                    copy.data = item.data.copy()
                collection = item.users_collection[0] if item.users_collection else bpy.context.collection
                collection.objects.link(copy)
                copy.name = f"{item.name}_mirror"
                copy.matrix_world = matrix @ item.matrix_world
                created.append(copy.name)
            else:
                item.matrix_world = matrix @ item.matrix_world
        bpy.context.view_layer.update()
        return {
            "success": True,
            "operation": "mirror",
            "axis": str(axis).upper(),
            "plane": float(plane),
            "duplicate": bool(duplicate),
            "created": created,
            "objects": [item.name for item in objects],
            "passed": True,
        }


HEAVY_COMMANDS = {
    "execute_code",
    "render_multiview_inspection",
    "render_scene",
    "download_polyhaven_asset",
    "download_sketchfab_model",
    "boolean_operation",
    "auto_fix_model",
    "fuse_organic_parts",
    "create_building_shell",
    "create_skeleton_skin_mesh",
    "generate_game_ready_asset",
    "build_3d_network_datacenter_from_pt",
}

# Blueprints universales con proporciones métricas y jerarquías estructurales
MODELING_BLUEPRINTS: Dict[str, Dict[str, Any]] = {
    "chair": {
        "dimensions": [0.50, 0.52, 0.88],
        "tolerance": 0.25,
        "parts": {
            "Seat": {"type": "ROUNDED_BOX", "dims": [0.46, 0.46, 0.04], "loc": [0, 0, 0.44], "origin": "BOTTOM"},
            "Backrest": {"type": "ROUNDED_BOX", "dims": [0.42, 0.03, 0.40], "loc": [0, 0.20, 0.48], "origin": "BOTTOM"},
        },
        "supports": {"thickness": 0.035, "height": 0.44, "inset_x": 0.04, "inset_y": 0.04, "taper_ratio": 0.75, "flare_angle_deg": 3.0},
        "bounds": {"aspect_xy": (0.8, 1.2), "seat_height_ratio": (0.45, 0.55)},
        "workflow": "Parametric Primitives + Corner Supports",
    },
    "table": {
        "dimensions": [1.40, 0.80, 0.75],
        "tolerance": 0.25,
        "parts": {
            "Tabletop": {"type": "ROUNDED_BOX", "dims": [1.40, 0.80, 0.04], "loc": [0, 0, 0.71], "origin": "BOTTOM"}
        },
        "supports": {"thickness": 0.05, "height": 0.71, "inset_x": 0.06, "inset_y": 0.06, "taper_ratio": 0.85},
        "bounds": {"aspect_xy": (1.4, 2.2), "height": (0.70, 0.80)},
        "workflow": "Parametric Primitives + Corner Supports",
    },
    "sofa": {
        "dimensions": [2.10, 0.90, 0.85],
        "tolerance": 0.25,
        "parts": {
            "Base": {"type": "ROUNDED_BOX", "dims": [2.00, 0.85, 0.20], "loc": [0, 0, 0.15], "origin": "BOTTOM"},
            "Seat_Cushion": {"type": "ROUNDED_BOX", "dims": [1.80, 0.65, 0.15], "loc": [0, -0.05, 0.35], "origin": "BOTTOM"},
            "Backrest": {"type": "ROUNDED_BOX", "dims": [1.80, 0.20, 0.50], "loc": [0, 0.30, 0.35], "origin": "BOTTOM"},
            "Armrest_L": {"type": "ROUNDED_BOX", "dims": [0.15, 0.80, 0.35], "loc": [-0.95, 0.0, 0.30], "origin": "BOTTOM"},
            "Armrest_R": {"type": "ROUNDED_BOX", "dims": [0.15, 0.80, 0.35], "loc": [0.95, 0.0, 0.30], "origin": "BOTTOM"},
        },
        "supports": {"thickness": 0.04, "height": 0.15, "inset_x": 0.08, "inset_y": 0.08},
        "bounds": {"aspect_xy": (1.8, 2.6)},
        "workflow": "Parametric Primitives + Deformers",
    },
    "car": {
        "dimensions": [4.50, 1.90, 1.45],
        "tolerance": 0.25,
        "parts": {
            "Chassis": {"type": "LOFT_OR_BOX", "dims": [4.30, 1.80, 0.45], "loc": [0, 0, 0.25], "origin": "CENTER"},
            "Cabin": {"type": "ROUNDED_BOX", "dims": [2.40, 1.50, 0.65], "loc": [-0.2, 0, 0.90], "origin": "CENTER"},
        },
        "wheels": {"radius": 0.34, "width": 0.22, "track": 1.70, "wheelbase": 2.70},
        "workflow": "create_loft_surface (Body) + create_lathe_part (Wheels) + symmetry_mirror",
    },
    "humanoid": {
        "dimensions": [0.65, 0.35, 1.80],
        "tolerance": 0.20,
        "landmarks": {
            "pelvis": [0.0, 0.0, 0.95],
            "spine": [0.0, 0.0, 1.15],
            "chest": [0.0, 0.0, 1.35],
            "neck": [0.0, 0.0, 1.52],
            "head": [0.0, 0.0, 1.70],
            "shoulder_L": [0.22, 0.0, 1.42],
            "shoulder_R": [-0.22, 0.0, 1.42],
            "elbow_L": [0.38, 0.0, 1.15],
            "elbow_R": [-0.38, 0.0, 1.15],
            "wrist_L": [0.45, 0.0, 0.88],
            "wrist_R": [-0.45, 0.0, 0.88],
            "knee_L": [0.12, 0.0, 0.50],
            "knee_R": [-0.12, 0.0, 0.50],
            "ankle_L": [0.12, 0.0, 0.08],
            "ankle_R": [-0.12, 0.0, 0.08],
        },
        "workflow": "create_skeleton_skin_mesh OR fuse_organic_parts -> auto_rig_humanoid",
    },
    "lamp": {
        "dimensions": [0.35, 0.35, 1.45],
        "tolerance": 0.25,
        "parts": {
            "Base": {"type": "LATHE", "radius": 0.16, "height": 0.04, "loc": [0, 0, 0.0]},
            "Pole": {"type": "SWEEP", "radius": 0.015, "height": 1.10, "loc": [0, 0, 0.04]},
            "Shade": {"type": "LATHE", "radius_top": 0.10, "radius_bot": 0.18, "height": 0.25, "loc": [0, 0, 1.20]},
        },
        "workflow": "create_lathe_part + create_curve_sweep",
    },
    "house": {
        "dimensions": [10.0, 8.0, 5.5],
        "tolerance": 0.35,
        "floors": 1,
        "floor_height": 2.8,
        "wall_thickness": 0.20,
        "roof_style": "GABLE",
        "pitch_deg": 28.0,
        "workflow": "create_floorplan_walls -> cut_wall_opening -> create_parametric_roof",
    },
    "building": {
        "dimensions": [16.0, 16.0, 24.0],
        "tolerance": 0.35,
        "floors": 7,
        "floor_height": 3.2,
        "window_grid": {"cols_x": 4, "cols_y": 4, "width": 1.6, "height": 1.9},
        "workflow": "create_building_shell + array_grid_on_surface",
    },
    "skyscraper": {
        "dimensions": [24.0, 24.0, 80.0],
        "tolerance": 0.35,
        "floors": 22,
        "floor_height": 3.4,
        "window_grid": {"cols_x": 6, "cols_y": 6, "width": 1.8, "height": 2.1},
        "workflow": "create_building_shell + array_grid_on_surface",
    },
}


# Presets extensibles para apply_smart_procedural_material: color base RGBA,
# parámetros Principled BSDF, color de desgaste de bordes e intensidad de bump.
SMART_MATERIAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "BRUSHED_METAL": {"color": [0.72, 0.73, 0.75, 1.0], "metallic": 1.0, "roughness": 0.38, "wear_color": [0.9, 0.9, 0.92, 1.0], "bump_strength": 0.12},
    "CAR_PAINT_METALLIC": {"color": [0.75, 0.04, 0.04, 1.0], "metallic": 0.85, "roughness": 0.22, "wear_color": [0.85, 0.85, 0.88, 1.0], "bump_strength": 0.03},
    "WEATHERED_WOOD": {"color": [0.45, 0.3, 0.18, 1.0], "metallic": 0.0, "roughness": 0.8, "wear_color": [0.62, 0.5, 0.36, 1.0], "bump_strength": 0.5},
    "MATTE_PLASTIC_EDGE_WEAR": {"color": [0.16, 0.17, 0.19, 1.0], "metallic": 0.0, "roughness": 0.65, "wear_color": [0.55, 0.56, 0.58, 1.0], "bump_strength": 0.08},
    "ARCHITECTURAL_GLASS": {"color": [0.75, 0.9, 0.95, 1.0], "metallic": 0.0, "roughness": 0.05, "transmission": 1.0, "alpha": 0.35, "wear_color": [1.0, 1.0, 1.0, 1.0], "bump_strength": 0.0},
}

# Perfiles de bevel para smart_bevel_and_polish: segmentos, ángulo límite y smooth.
SMART_BEVEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "HARD_SURFACE": {"segments": 2, "angle_deg": 30.0, "smooth": False},
    "ORGANIC": {"segments": 3, "angle_deg": 45.0, "smooth": True},
    "ARCHITECTURAL": {"segments": 1, "angle_deg": 30.0, "smooth": False},
}

# Colores de cableado por tipo de cable PT para el datacenter.
PT_CABLE_COLORS: Dict[str, List[float]] = {
    "straight": [0.10, 0.30, 0.95, 1.0],
    "cross": [1.00, 0.50, 0.05, 1.0],
    "serial": [0.90, 0.08, 0.08, 1.0],
    "fiber": [0.05, 0.90, 0.90, 1.0],
}

# Categorías PT que van en rack; el resto se trata como host de escritorio.
PT_RACK_CATEGORIES = {"switch", "router", "server", "firewall", "hub", "wlc", "modem", "patch_panel", "cloud"}


# ==============================================================================
# BLENDER MCP SERVER CORE CLASS
# ==============================================================================+
class BlenderMCPServer:
    """Core Engine communicating with the FastMCP Python client via raw TCP sockets."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.running = False
        self.accepting_requests = False
        self.server_socket: Optional[socket.socket] = None
        self.server_thread: Optional[threading.Thread] = None
        self.checkpoint_dir = tempfile.mkdtemp(prefix="blendermcp_checkpoints_")
        self.checkpoints: Dict[str, Dict[str, Any]] = {}

        # Concurrency & Rate Limiting Protection
        self.rate_limit_lock = threading.Lock()
        self.request_times: List[float] = []
        self.heavy_request_times: List[float] = []

        # Main-thread queue. Only the timer registered on Blender's main
        # thread touches bpy; socket threads only enqueue.
        self.request_queue: "queue.Queue[PendingRequest]" = queue.Queue()
        self.client_slots = threading.BoundedSemaphore(MAX_CLIENTS)
        self.main_thread_timer_registered = False
        self.last_dispatch_thread: Optional[str] = None
        self.auth_token: Optional[str] = None
        self._main_thread_timer = self._drain_main_thread_queue

    def start(self):
        if self.running:
            return True
        if bpy.app.background:
            print("[BlenderMCP-Pro] Cannot serve commands in Blender background mode: timers do not run. Use a GUI session or xvfb-run.")
            return False
        if threading.current_thread() is not threading.main_thread():
            print("[BlenderMCP-Pro] start() must be called from Blender's main thread.")
            return False
        try:
            self.auth_token = load_or_create_auth_token()
        except OSError as exc:
            print(f"[BlenderMCP-Pro] Cannot create or read the auth token: {exc}")
            return False
        if not self.auth_token and os.environ.get(ALLOW_NO_AUTH_ENV_VAR) != "1":
            print("[BlenderMCP-Pro] Refusing to start without authentication. Set BLENDER_MCP_ALLOW_NO_AUTH=1 only for trusted local use.")
            return False
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
        except OSError as exc:
            with suppress(Exception):
                self.server_socket.close()
            self.server_socket = None
            print(f"[BlenderMCP-Pro] Cannot bind {self.host}:{self.port} ({exc}). Another Blender instance is already serving on that port.")
            return False
        self.port = self.server_socket.getsockname()[1]
        self.running = True
        self.accepting_requests = True
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()
        try:
            self._register_main_thread_timer()
        except Exception as exc:
            print(f"[BlenderMCP-Pro] Cannot register the main-thread timer: {exc}")
            self.stop()
            return False
        print(f"[BlenderMCP-Pro] Server listening on {self.host}:{self.port}")
        if self.auth_token:
            print(f"[BlenderMCP-Pro] Auth token file: {default_token_path()}")
        else:
            print("[BlenderMCP-Pro] WARNING: authentication disabled by BLENDER_MCP_ALLOW_NO_AUTH=1")
        return True

    def stop(self):
        self.running = False
        self.accepting_requests = False
        if self.server_socket:
            with suppress(Exception):
                self.server_socket.close()
            self.server_socket = None
        if self.server_thread:
            self.server_thread.join(timeout=2.0)
            self.server_thread = None
        self._fail_pending_requests("Server stopped")
        if threading.current_thread() is threading.main_thread():
            self._unregister_main_thread_timer()
        print("[BlenderMCP-Pro] Server stopped.")

    def _register_main_thread_timer(self):
        if self.main_thread_timer_registered:
            return
        bpy.app.timers.register(
            self._main_thread_timer,
            first_interval=MAIN_THREAD_TICK_SECONDS,
            persistent=True,
        )
        self.main_thread_timer_registered = True

    def _unregister_main_thread_timer(self):
        if not self.main_thread_timer_registered:
            return
        with suppress(Exception):
            bpy.app.timers.unregister(self._main_thread_timer)
        self.main_thread_timer_registered = False

    def _drain_main_thread_queue(self):
        if not self.running:
            self.main_thread_timer_registered = False
            return None
        if threading.current_thread() is not threading.main_thread():
            print("[BlenderMCP-Pro] Queue drained from a non-main thread; stopping.")
            self.running = False
            self.main_thread_timer_registered = False
            return None

        self.last_dispatch_thread = threading.current_thread().name
        processed = 0
        while processed < MAX_REQUESTS_PER_TICK:
            try:
                pending = self.request_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if pending.done.is_set():
                continue
            try:
                result = self._execute_command_internal(pending.cmd_type, pending.params)
                pending.response = {"status": "success", "result": result}
            except Exception as ex:
                err_trace = traceback.format_exc()
                print(f"[BlenderMCP Error] {err_trace}")
                pending.response = {"status": "error", "message": str(ex), "traceback": err_trace}
            finally:
                pending.done.set()
        return MAIN_THREAD_TICK_SECONDS

    def _fail_pending_requests(self, message: str):
        while True:
            try:
                pending = self.request_queue.get_nowait()
            except queue.Empty:
                break
            if not pending.done.is_set():
                pending.response = {"status": "error", "message": message}
                pending.done.set()

    def _server_loop(self):
        while self.running:
            try:
                client_sock, client_addr = self.server_socket.accept()
                if not self.client_slots.acquire(blocking=False):
                    with suppress(Exception):
                        client_sock.sendall(
                            json.dumps({"status": "error", "message": f"Too many clients (max {MAX_CLIENTS})"}).encode("utf-8") + b"\n"
                        )
                        client_sock.close()
                    continue
                t = threading.Thread(target=self._handle_client_wrapper, args=(client_sock, client_addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[BlenderMCP-Pro] Accept error: {e}")
                break

    def _handle_client_wrapper(self, client: socket.socket, addr: Tuple[str, int]):
        try:
            self._handle_client(client, addr)
        finally:
            self.client_slots.release()

    def _check_rate_limit(self, cmd_type: str) -> Optional[str]:
        now = time.time()
        with self.rate_limit_lock:
            self.request_times = [t for t in self.request_times if now - t < 60.0]
            self.heavy_request_times = [t for t in self.heavy_request_times if now - t < 60.0]

            is_heavy = cmd_type in HEAVY_COMMANDS
            if len(self.request_times) >= 600:
                return "Global rate limit exceeded (max 600 req/min)"
            if is_heavy and len(self.heavy_request_times) >= 30:
                return f"Heavy command rate limit exceeded for '{cmd_type}' (max 30 req/min)"

            self.request_times.append(now)
            if is_heavy:
                self.heavy_request_times.append(now)
        return None

    def _handle_client(self, client: socket.socket, addr: Tuple[str, int]):
        client_send_lock = threading.Lock()
        client.settimeout(180.0)
        buffer = b""
        decoder = json.JSONDecoder()

        def send_response(data: Dict[str, Any], request_id: Any = None):
            if request_id is not None:
                data = dict(data)
                data["request_id"] = request_id
            payload = json.dumps(data).encode("utf-8") + b"\n"
            if len(payload) > MAX_RESPONSE_BYTES:
                payload = json.dumps({
                    "status": "error",
                    "message": f"Response exceeds maximum size ({MAX_RESPONSE_BYTES} bytes)",
                    "request_id": request_id,
                }).encode("utf-8") + b"\n"
            with client_send_lock:
                client.sendall(payload)

        try:
            while self.running:
                chunk = client.recv(BUFFER_SIZE)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > MAX_MESSAGE_BYTES:
                    send_response({
                        "status": "error",
                        "message": f"Request exceeds maximum size ({MAX_MESSAGE_BYTES} bytes)",
                    })
                    return

                # Parse every complete JSON value in the buffer. TCP may
                # coalesce two requests into one recv; decoding the whole
                # buffer as a single object would drop both of them.
                while self.running:
                    try:
                        text = buffer.decode("utf-8")
                    except UnicodeDecodeError:
                        break  # incomplete multi-byte sequence, wait for more

                    stripped = text.lstrip()
                    if not stripped:
                        buffer = b""
                        break

                    try:
                        msg, end = decoder.raw_decode(stripped)
                    except json.JSONDecodeError:
                        break  # incomplete JSON, wait for more

                    consumed = len(text) - len(stripped) + len(stripped[:end].encode("utf-8"))
                    buffer = buffer[consumed:]

                    if not isinstance(msg, dict):
                        send_response({"status": "error", "message": "Request must be a JSON object"})
                        continue

                    request_id = msg.get("request_id")
                    expected_token = self.auth_token or ""
                    if expected_token:
                        if not hmac.compare_digest(str(msg.get("auth_token", "")), expected_token):
                            send_response({"status": "error", "message": "Authentication failed: invalid or missing token"}, request_id)
                            return
                    elif os.environ.get(ALLOW_NO_AUTH_ENV_VAR) != "1":
                        send_response({"status": "error", "message": "Server has no auth token; refusing request"}, request_id)
                        return

                    cmd_type = msg.get("type", "")
                    params = msg.get("params", {})
                    if not isinstance(params, dict):
                        send_response({"status": "error", "message": "'params' must be a JSON object"}, request_id)
                        continue

                    rate_err = self._check_rate_limit(cmd_type)
                    if rate_err:
                        send_response({"status": "error", "message": rate_err}, request_id)
                        continue

                    if not self.accepting_requests:
                        send_response({"status": "error", "message": "Server is stopping"}, request_id)
                        return

                    pending = PendingRequest(cmd_type=cmd_type, params=params, request_id=request_id)
                    self.request_queue.put(pending)
                    if not self.accepting_requests and not pending.done.is_set():
                        pending.response = {"status": "error", "message": "Server is stopping"}
                        pending.done.set()
                    pending.done.wait(timeout=175.0)

                    resp = pending.response or {"status": "error", "message": "Operation timed out in Blender"}
                    send_response(resp, request_id)

        except Exception as ex:
            print(f"[BlenderMCP-Pro] Client handler exception: {ex}")
        finally:
            with suppress(Exception):
                client.close()

    # ==========================================================================
    # INTERNAL GEOMETRY, DEPSGRAPH & BVHTREE SPATIAL HELPERS
    # ==========================================================================
    @staticmethod
    def _get_aabb(obj: bpy.types.Object) -> List[List[float]]:
        """Calcula el Bounding Box ortogonal mundial exacto evaluado con depsgraph y modificadores."""
        if obj.type != "MESH":
            raise TypeError(f"Object '{obj.name}' must be a MESH (got {obj.type})")
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            if mesh and len(mesh.vertices) > 0:
                mat = eval_obj.matrix_world
                world_verts = [mat @ v.co for v in mesh.vertices]
                min_c = Vector((min(v.x for v in world_verts), min(v.y for v in world_verts), min(v.z for v in world_verts)))
                max_c = Vector((max(v.x for v in world_verts), max(v.y for v in world_verts), max(v.z for v in world_verts)))
            else:
                local_bbox = [Vector(corner) for corner in obj.bound_box]
                world_bbox = [obj.matrix_world @ corner for corner in local_bbox]
                min_c = Vector(map(min, zip(*world_bbox)))
                max_c = Vector(map(max, zip(*world_bbox)))
        finally:
            eval_obj.to_mesh_clear()

        return [[round(float(c), 5) for c in min_c], [round(float(c), 5) for c in max_c]]

    @staticmethod
    def _build_world_bvh(obj: bpy.types.Object) -> Tuple[BVHTree, List[Vector], int]:
        """Construye un árbol BVHTree en coordenadas mundiales a partir de la malla evaluada."""
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        bm = bmesh.new()
        try:
            bm.from_object(eval_obj, depsgraph)
            bm.transform(eval_obj.matrix_world)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bvh = BVHTree.FromBMesh(bm, epsilon=0.0001)
            verts_world = [v.co.copy() for v in bm.verts]
            face_count = max(1, len(bm.faces))
            return bvh, verts_world, face_count
        finally:
            bm.free()

    @classmethod
    def _compute_aabb_gap_and_delta(cls, aabb_a: List[List[float]], aabb_b: List[List[float]]) -> Tuple[float, List[float]]:
        min_a, max_a = Vector(aabb_a[0]), Vector(aabb_a[1])
        min_b, max_b = Vector(aabb_b[0]), Vector(aabb_b[1])
        delta = [0.0, 0.0, 0.0]
        gap_sq = 0.0
        for i in range(3):
            if max_a[i] < min_b[i]:
                d = min_b[i] - max_a[i]
                gap_sq += d * d
                delta[i] = d
            elif max_b[i] < min_a[i]:
                d = min_a[i] - max_b[i]
                gap_sq += d * d
                delta[i] = -d
        return math.sqrt(gap_sq), [round(x, 5) for x in delta]

    @classmethod
    @staticmethod
    def _is_face_contact(aabb_a: List[List[float]], aabb_b: List[List[float]],
                         tol: float = 0.002) -> bool:
        """True si dos AABB se apoyan cara con cara sin compartir volumen.

        Junta intencional (muro sobre piso, caja sobre mesa): las caras se tocan
        en un eje mientras en los otros dos hay solape interior. La tolerancia
        (2mm) queda por debajo de la soldadura estándar de 4mm, así que un weld
        nunca se confunde con contacto. Ante ambigüedad devuelve False (el par
        sigue a SEVERE_OVERLAP para revisión).
        """
        for i in range(3):
            a_min, a_max = aabb_a[0][i], aabb_a[1][i]
            b_min, b_max = aabb_b[0][i], aabb_b[1][i]
            if not (abs(a_max - b_min) <= tol or abs(b_max - a_min) <= tol):
                continue
            others = [j for j in range(3) if j != i]
            if all(min(aabb_a[1][j], aabb_b[1][j]) - max(aabb_a[0][j], aabb_b[0][j]) > tol
                   for j in others):
                return True
        return False

    @staticmethod
    def _is_volumetric_overlap(aabb_a: List[List[float]], aabb_b: List[List[float]],
                               frac: float = 0.25) -> bool:
        """True si los volúmenes se interpenetran de verdad en los 3 ejes.

        Complementa el ratio de caras BVH (que toma el mínimo y esconde una
        pieza chica hundida en una grande). Un weld de 4mm sobre piezas de
        muebles queda muy por debajo del 25% del eje menor, así que el
        comportamiento de mobiliario no cambia.
        """
        for i in range(3):
            depth = min(aabb_a[1][i], aabb_b[1][i]) - max(aabb_a[0][i], aabb_b[0][i])
            smallest = min(aabb_a[1][i] - aabb_a[0][i], aabb_b[1][i] - aabb_b[0][i])
            if smallest <= 1e-9 or depth / smallest <= frac:
                return False
        return True

    def _compute_surface_gap_and_overlap(
        cls,
        obj_a: bpy.types.Object,
        obj_b: bpy.types.Object,
        aabb_a: Optional[List[List[float]]] = None,
        aabb_b: Optional[List[List[float]]] = None,
    ) -> Tuple[float, List[float], float]:
        """Calcula la distancia superficial real, vector de contacto y ratio de penetración poligonal con BVHTree."""
        if aabb_a is None:
            aabb_a = cls._get_aabb(obj_a)
        if aabb_b is None:
            aabb_b = cls._get_aabb(obj_b)

        aabb_gap, aabb_delta = cls._compute_aabb_gap_and_delta(aabb_a, aabb_b)
        if aabb_gap > 0.6:
            return aabb_gap, aabb_delta, 0.0

        try:
            bvh_a, verts_a, faces_a = cls._build_world_bvh(obj_a)
            bvh_b, verts_b, faces_b = cls._build_world_bvh(obj_b)

            overlapping_pairs = bvh_a.overlap(bvh_b)
            if overlapping_pairs:
                unique_a = len({pair[0] for pair in overlapping_pairs})
                unique_b = len({pair[1] for pair in overlapping_pairs})
                overlap_ratio = min(unique_a / faces_a, unique_b / faces_b)
                return 0.0, [0.0, 0.0, 0.0], round(overlap_ratio, 4)

            best_dist = float("inf")
            best_delta = Vector((0.0, 0.0, 0.0))

            step_a = max(1, len(verts_a) // 200)
            for v_a in verts_a[::step_a]:
                loc_b, _n, _i, dist = bvh_b.find_nearest(v_a)
                if loc_b is not None and dist < best_dist:
                    best_dist = dist
                    best_delta = loc_b - v_a

            step_b = max(1, len(verts_b) // 200)
            for v_b in verts_b[::step_b]:
                loc_a, _n, _i, dist = bvh_a.find_nearest(v_b)
                if loc_a is not None and dist < best_dist:
                    best_dist = dist
                    best_delta = v_b - loc_a

            if best_dist < float("inf"):
                return round(float(best_dist), 5), [round(float(c), 5) for c in best_delta], 0.0
        except Exception as e:
            print(f"[BlenderMCP Warning] BVH proximity fallback: {e}")

        return aabb_gap, aabb_delta, 0.0

    @staticmethod
    def _auto_box_uv_unwrap(mesh: bpy.types.Mesh, scale: float = 1.0):
        """Genera un desempaquetado UV cúbico métrico triplanar automático en BMesh."""
        if not mesh or len(mesh.polygons) == 0:
            return
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()

        for face in bm.faces:
            norm = face.normal
            nx, ny, nz = abs(norm.x), abs(norm.y), abs(norm.z)
            for loop in face.loops:
                co = loop.vert.co
                if nx >= ny and nx >= nz:
                    u = co.y * scale
                    v = co.z * scale
                elif ny >= nx and ny >= nz:
                    u = co.x * scale
                    v = co.z * scale
                else:
                    u = co.x * scale
                    v = co.y * scale
                loop[uv_layer].uv = (float(u), float(v))

        bm.to_mesh(mesh)
        mesh.update()
        bm.free()

    @staticmethod
    def _set_mesh_origin(obj: bpy.types.Object, origin_mode: str = "BOTTOM"):
        """Ajusta el origen geométrico del objeto sin desplazar a sus hijos."""
        if obj.type != "MESH" or not obj.data or len(obj.data.vertices) == 0:
            return
        mesh = obj.data
        verts = mesh.vertices
        min_z = min(v.co.z for v in verts)
        max_z = max(v.co.z for v in verts)
        min_x = min(v.co.x for v in verts)
        max_x = max(v.co.x for v in verts)
        min_y = min(v.co.y for v in verts)
        max_y = max(v.co.y for v in verts)

        if origin_mode == "BOTTOM":
            shift = Vector(((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, min_z))
        elif origin_mode == "TOP":
            shift = Vector(((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, max_z))
        else:  # CENTER
            shift = Vector(((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, (min_z + max_z) / 2.0))

        if shift.length > 1e-5:
            for v in verts:
                v.co -= shift
            mesh.update()
            world_shift = obj.matrix_world.to_3x3() @ shift
            obj.location += world_shift

    def _create_or_reuse_mesh_object(
        self,
        name: str,
        mesh: bpy.types.Mesh,
        location: List[float],
        rotation_deg: List[float],
        origin_mode: str = "BOTTOM",
        parent_name: Optional[str] = None,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
    ) -> bpy.types.Object:
        """Crea o actualiza un objeto MESH preservando matrices mundiales de los hijos y asignando materiales."""
        self._auto_box_uv_unwrap(mesh)
        existing = bpy.data.objects.get(name)
        old_mesh = existing.data if (existing and existing.type == "MESH") else None

        if existing and existing.type == "MESH":
            children_world = [(c, c.matrix_world.copy()) for c in existing.children]
            obj = existing
            obj.data = mesh
            obj.modifiers.clear()
            if old_mesh and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
        else:
            if existing:
                bpy.data.objects.remove(existing, do_unlink=True)
            children_world = []
            obj = bpy.data.objects.new(name, mesh)
            bpy.context.collection.objects.link(obj)

        obj.scale = Vector((1.0, 1.0, 1.0))
        self._set_mesh_origin(obj, origin_mode=origin_mode)
        obj.location = Vector((float(location[0]), float(location[1]), float(location[2])))
        obj.rotation_euler = Euler((
            math.radians(float(rotation_deg[0])),
            math.radians(float(rotation_deg[1])),
            math.radians(float(rotation_deg[2])),
        ), "XYZ")
        bpy.context.view_layer.update()

        for child_obj, child_mat in children_world:
            child_obj.matrix_parent_inverse = obj.matrix_world.inverted()
            child_obj.matrix_world = child_mat

        if parent_name:
            p_obj = bpy.data.objects.get(parent_name)
            if p_obj:
                obj.parent = p_obj
                obj.matrix_parent_inverse = p_obj.matrix_world.inverted()

        if material_name:
            self.assign_material(obj.name, material_name)
        elif color:
            mat_name = f"Mat_{name}"
            self.create_material(mat_name, color=color)
            self.assign_material(obj.name, mat_name)

        return obj

    # ==========================================================================
    # DISPATCHER TABLE
    # ==========================================================================
    def _execute_command_internal(self, cmd_type: str, params: Dict[str, Any]) -> Any:
        handlers = {
            # Scene & Blueprint Inspection
            "get_scene_info": lambda p: self.get_scene_info(**p),
            "get_object_info": lambda p: self.get_object_info(**p),
            "list_objects": lambda p: self.list_objects(**p),
            "list_modeling_blueprints": lambda p: self.list_modeling_blueprints(**p),
            "get_modeling_blueprint": lambda p: self.get_modeling_blueprint(**p),
            # Parametric Modeling Primitives & Assemblies
            "create_parametric_part": lambda p: self.create_parametric_part(**p),
            "create_assembly": lambda p: self.create_assembly(**p),
            "update_assembly": lambda p: self.update_assembly(**p),
            "attach_and_align": lambda p: self.attach_and_align(**p),
            "snap_to_semantic_anchor": lambda p: self.snap_to_semantic_anchor(**p),
            "list_semantic_anchors": lambda p: self.list_semantic_anchors(**p),
            "anchor_operation": lambda p: self.anchor_operation(**p),
            "validate_constraints": lambda p: self.validate_constraints(**p),
            "orient_and_face_towards": lambda p: self.orient_and_face_towards(**p),
            "spawn_corner_supports": lambda p: self.spawn_corner_supports(**p),
            "symmetry_mirror": lambda p: self.symmetry_mirror(**p),
            "radial_array": lambda p: self.radial_array(**p),
            "boolean_operation": lambda p: self.boolean_operation(**p),
            "create_articulation_joint": lambda p: self.create_articulation_joint(**p),
            # Curvature, Lathe, Sweep, Loft & Deformers
            "create_lathe_part": lambda p: self.create_lathe_part(**p),
            "create_curve_sweep": lambda p: self.create_curve_sweep(**p),
            "create_loft_surface": lambda p: self.create_loft_surface(**p),
            "deform_object": lambda p: self.deform_object(**p),
            # Organic Modeling, Skinning & Rigging
            "fuse_organic_parts": lambda p: self.fuse_organic_parts(**p),
            "create_skeleton_skin_mesh": lambda p: self.create_skeleton_skin_mesh(**p),
            "auto_rig_humanoid": lambda p: self.auto_rig_humanoid(**p),
            # Parametric Architecture & Buildings
            "create_floorplan_walls": lambda p: self.create_floorplan_walls(**p),
            "cut_wall_opening": lambda p: self.cut_wall_opening(**p),
            "create_parametric_roof": lambda p: self.create_parametric_roof(**p),
            "create_staircase": lambda p: self.create_staircase(**p),
            "create_building_shell": lambda p: self.create_building_shell(**p),
            "array_grid_on_surface": lambda p: self.array_grid_on_surface(**p),
            # Audit, Topology Repair & Self-Correction
            "audit_3d_model": lambda p: self.audit_3d_model(**p),
            "repair_mesh_geometry": lambda p: self.repair_mesh_geometry(**p),
            "ground_model": lambda p: self.ground_model(**p),
            "auto_fix_model": lambda p: self.auto_fix_model(**p),
            "place_on_surface_raycast": lambda p: self.place_on_surface_raycast(**p),
            "smart_bevel_and_polish": lambda p: self.smart_bevel_and_polish(**p),
            "apply_smart_procedural_material": lambda p: self.apply_smart_procedural_material(**p),
            "generate_game_ready_asset": lambda p: self.generate_game_ready_asset(**p),
            "build_3d_network_datacenter_from_pt": lambda p: self.build_3d_network_datacenter_from_pt(**p),
            # Visual Critic & Studio Lighting
            "render_multiview_inspection": lambda p: self.render_multiview_inspection(**p),
            "setup_studio_lighting": lambda p: self.setup_studio_lighting(**p),
            # Transforms, Materials & Scene
            "transform_object": lambda p: self.transform_object(**p),
            "delete_object": lambda p: self.delete_object(**p),
            "duplicate_object": lambda p: self.duplicate_object(**p),
            "create_material": lambda p: self.create_material(**p),
            "assign_material": lambda p: self.assign_material(**p),
            "clear_scene": lambda p: self.clear_scene(**p),
            "export_scene": lambda p: self.export_scene(**p),
            "execute_code": lambda p: self.execute_code(**p),
            "create_checkpoint": lambda p: self.create_checkpoint(**p),
            "rollback_checkpoint": lambda p: self.rollback_checkpoint(**p),
            "list_checkpoints": lambda p: self.list_checkpoints(**p),
            # External Assets (Poly Haven & Sketchfab)
            "search_polyhaven_assets": lambda p: self.search_polyhaven_assets(**p),
            "download_polyhaven_asset": lambda p: self.download_polyhaven_asset(**p),
            "search_sketchfab_models": lambda p: self.search_sketchfab_models(**p),
            "download_sketchfab_model": lambda p: self.download_sketchfab_model(**p),
        }

        if cmd_type not in handlers:
            raise ValueError(f"Unknown command type '{cmd_type}'.")
        return handlers[cmd_type](params)

    # ==========================================================================
    # 1. SCENE & BLUEPRINT INSPECTION
    # ==========================================================================
    def get_scene_info(self, max_objects: int = 100) -> Dict[str, Any]:
        bpy.context.view_layer.update()
        objects = []
        for obj in list(bpy.context.scene.objects)[:max_objects]:
            info = {
                "name": obj.name,
                "type": obj.type,
                "location": [round(c, 4) for c in obj.location],
                "rotation_euler_deg": [round(math.degrees(c), 2) for c in obj.rotation_euler],
                "scale": [round(c, 4) for c in obj.scale],
                "parent": obj.parent.name if obj.parent else None,
                "children": [c.name for c in obj.children],
            }
            if obj.type == "MESH":
                with suppress(Exception):
                    aabb = self._get_aabb(obj)
                    info["world_aabb"] = aabb
                    info["dimensions"] = [round(aabb[1][i] - aabb[0][i], 4) for i in range(3)]
                    info["vertex_count"] = len(obj.data.vertices)
                    info["polygon_count"] = len(obj.data.polygons)
            objects.append(info)

        return {
            "object_count": len(bpy.context.scene.objects),
            "active_object": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
            "objects": objects,
        }

    def get_object_info(self, name: str) -> Dict[str, Any]:
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        bpy.context.view_layer.update()
        info = {
            "name": obj.name,
            "type": obj.type,
            "location": [round(c, 4) for c in obj.location],
            "rotation_euler_deg": [round(math.degrees(c), 2) for c in obj.rotation_euler],
            "scale": [round(c, 4) for c in obj.scale],
            "parent": obj.parent.name if obj.parent else None,
            "children": [c.name for c in obj.children],
            "materials": [slot.material.name for slot in obj.material_slots if slot.material],
        }
        if obj.type == "MESH":
            aabb = self._get_aabb(obj)
            info["world_aabb"] = aabb
            info["dimensions"] = [round(aabb[1][i] - aabb[0][i], 4) for i in range(3)]
            info["vertex_count"] = len(obj.data.vertices)
            info["polygon_count"] = len(obj.data.polygons)
        return info

    def list_objects(self, type_filter: Optional[str] = None) -> List[str]:
        if type_filter:
            return [o.name for o in bpy.context.scene.objects if o.type == type_filter.upper()]
        return [o.name for o in bpy.context.scene.objects]

    def list_modeling_blueprints(self) -> Dict[str, Any]:
        return MODELING_BLUEPRINTS

    def get_modeling_blueprint(self, category: str, target_height: Optional[float] = None) -> Dict[str, Any]:
        cat_lower = category.lower().strip()
        bp = MODELING_BLUEPRINTS.get(cat_lower)
        if not bp:
            return {
                "category": category,
                "message": f"Custom blueprint for '{category}'. Follow conventions: Ground at Z=0.0, Bilateral symmetry on X=0, Front is -Y.",
                "conventions": {"ground": "Z=0.0", "front": "-Y", "up": "+Z", "right": "+X"},
            }

        res = dict(bp)
        if target_height and "dimensions" in res:
            curr_h = res["dimensions"][2]
            scale_fac = target_height / curr_h
            res["dimensions"] = [round(d * scale_fac, 4) for d in res["dimensions"]]
            res["target_scale_applied"] = round(scale_fac, 4)
        return res

    # ==========================================================================
    # 2. PARAMETRIC & RELATIONAL MODELING TOOLS
    # ==========================================================================
    def create_parametric_part(
        self,
        name: str,
        shape: str = "ROUNDED_BOX",
        dimensions: List[float] = [0.5, 0.5, 0.5],
        location: List[float] = [0.0, 0.0, 0.0],
        rotation_deg: List[float] = [0.0, 0.0, 0.0],
        origin: str = "BOTTOM",
        bevel_width: float = 0.005,
        bevel_segments: int = 3,
        subsurf_levels: int = 0,
        taper_ratio: float = 0.7,
        thickness: float = 0.05,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
        parent_name: Optional[str] = None,
        segments: int = 32,
    ) -> Dict[str, Any]:
        dx, dy, dz = [float(abs(d)) for d in dimensions]
        mesh = bpy.data.meshes.new(name=f"{name}_Mesh")
        bm = bmesh.new()

        shape_upper = shape.upper()
        if shape_upper in ("BOX", "ROUNDED_BOX"):
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=Vector((dx, dy, dz)), verts=bm.verts[:])
        elif shape_upper == "CYLINDER":
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=segments,
                radius1=dx / 2.0, radius2=dx / 2.0, depth=dz
            )
            bmesh.ops.scale(bm, vec=Vector((1.0, dy / dx if dx > 0 else 1.0, 1.0)), verts=bm.verts[:])
        elif shape_upper == "TAPERED_CYLINDER":
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=segments,
                radius1=dx / 2.0, radius2=(dx / 2.0) * float(taper_ratio), depth=dz
            )
            bmesh.ops.scale(bm, vec=Vector((1.0, dy / dx if dx > 0 else 1.0, 1.0)), verts=bm.verts[:])
        elif shape_upper == "SPHERE":
            bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=max(16, segments // 2), radius=dx / 2.0)
            bmesh.ops.scale(bm, vec=Vector((1.0, dy / dx if dx > 0 else 1.0, dz / dx if dx > 0 else 1.0)), verts=bm.verts[:])
        elif shape_upper == "CAPSULE":
            r = min(dx, dy) / 2.0
            cyl_len = max(0.001, dz - 2 * r)
            bmesh.ops.create_cone(bm, cap_ends=False, segments=segments, radius1=r, radius2=r, depth=cyl_len)
            # Top Dome
            bm_top = bmesh.new()
            bmesh.ops.create_uvsphere(bm_top, u_segments=segments, v_segments=16, radius=r)
            bmesh.ops.translate(bm_top, vec=Vector((0, 0, cyl_len / 2.0)), verts=bm_top.verts[:])
            verts_to_keep = [v for v in bm_top.verts if v.co.z >= cyl_len / 2.0 - 0.0001]
            bmesh.ops.delete(bm_top, geom=[v for v in bm_top.verts if v not in verts_to_keep], context="VERTS")
            for f in bm_top.faces:
                bm.faces.new([bm.verts.new(v.co) for v in f.verts])
            bm_top.free()
            bmesh.ops.scale(bm, vec=Vector((dx / (2 * r), dy / (2 * r), 1.0)), verts=bm.verts[:])
        elif shape_upper == "TORUS":
            major_r = dx / 2.0
            minor_r = max(0.005, thickness / 2.0)
            # Torus via Spin
            bmesh.ops.create_circle(bm, cap_ends=False, segments=16, radius=minor_r)
            bmesh.ops.translate(bm, vec=Vector((major_r, 0, 0)), verts=bm.verts[:])
            bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], cent=(0, 0, 0), axis=(0, 0, 1), angle=math.radians(360.0), steps=segments, use_merge=True)
        elif shape_upper == "TUBE":
            outer_r = dx / 2.0
            inner_r = max(0.001, outer_r - thickness)
            bmesh.ops.create_cone(bm, cap_ends=False, segments=segments, radius1=outer_r, radius2=outer_r, depth=dz)
            bm_inner = bmesh.new()
            bmesh.ops.create_cone(bm_inner, cap_ends=False, segments=segments, radius1=inner_r, radius2=inner_r, depth=dz)
            for f in bm_inner.faces:
                bm.faces.new([bm.verts.new(v.co) for v in reversed(f.verts)])
            bm_inner.free()
        elif shape_upper == "WEDGE":
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=Vector((dx, dy, dz)), verts=bm.verts[:])
            top_front_verts = [v for v in bm.verts if v.co.y < 0 and v.co.z > 0]
            for v in top_front_verts:
                v.co.z = -dz / 2.0
        else:  # Fallback CUBE
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=Vector((dx, dy, dz)), verts=bm.verts[:])

        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh, location=location, rotation_deg=rotation_deg,
            origin_mode=origin, parent_name=parent_name, color=color, material_name=material_name
        )

        if shape_upper == "ROUNDED_BOX" or bevel_width > 0:
            bw = min(bevel_width, min(dx, dy, dz) * 0.45)
            if bw > 0.0005:
                bev = obj.modifiers.new(name="Bevel", type="BEVEL")
                bev.width = bw
                bev.segments = bevel_segments
                bev.limit_method = "ANGLE"
                bev.angle_limit = math.radians(35.0)

        if subsurf_levels > 0:
            sub = obj.modifiers.new(name="Subsurf", type="SUBSURFACE")
            sub.levels = subsurf_levels
            sub.render_levels = subsurf_levels

        aabb = self._get_aabb(obj)
        return {
            "success": True,
            "name": obj.name,
            "shape": shape_upper,
            "world_aabb": aabb,
            "dimensions": [round(aabb[1][i] - aabb[0][i], 4) for i in range(3)],
        }

    @staticmethod
    def _deep_merge(base: Any, patch: Any) -> Any:
        if isinstance(base, dict) and isinstance(patch, dict):
            merged = dict(base)
            for key, value in patch.items():
                merged[key] = BlenderMCPServer._deep_merge(merged.get(key), value)
            return merged
        return patch

    @staticmethod
    def _component_dimensions(component: Dict[str, Any]) -> List[float]:
        if "dimensions_mm" in component:
            values = [float(value) / 1000.0 for value in component["dimensions_mm"]]
        else:
            values = [float(value) for value in component.get("dimensions", [0.5, 0.5, 0.5])]
        if len(values) != 3 or any(value <= 0.0 for value in values):
            raise ValueError("Component dimensions must be three positive numbers")
        return values

    def _assembly_component_specs(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        assembly_type = str(spec.get("type", "assembly")).strip().lower()
        if assembly_type == "desk" and isinstance(spec.get("dimensions_mm"), dict):
            dimensions = spec["dimensions_mm"]
            width = max(float(dimensions.get("width", 1600)) / 1000.0, 0.1)
            depth = max(float(dimensions.get("depth", 800)) / 1000.0, 0.1)
            height = max(float(dimensions.get("height", 750)) / 1000.0, 0.1)
            top_thickness = min(0.04, max(0.02, height * 0.04))
            leg_size = min(0.08, max(0.04, width * 0.04))
            inset = min(0.08, max(0.02, min(width, depth) * 0.06))
            leg_height = max(0.05, height - top_thickness)
            materials = spec.get("materials") if isinstance(spec.get("materials"), dict) else {}
            top_color = materials.get("top")
            leg_color = materials.get("legs")
            components = [{
                "name": "Top",
                "shape": "BOX",
                "dimensions": [width, depth, top_thickness],
                "location": [0.0, 0.0, leg_height],
                "origin": "BOTTOM",
                "color": top_color,
            }]
            offset_x = width / 2.0 - inset - leg_size / 2.0
            offset_y = depth / 2.0 - inset - leg_size / 2.0
            for label, side_x, side_y in (
                ("Leg_FL", -1, -1),
                ("Leg_FR", 1, -1),
                ("Leg_BL", -1, 1),
                ("Leg_BR", 1, 1),
            ):
                components.append({
                    "name": label,
                    "shape": "BOX",
                    "dimensions": [leg_size, leg_size, leg_height],
                    "location": [side_x * offset_x, side_y * offset_y, 0.0],
                    "origin": "BOTTOM",
                    "color": leg_color,
                })
            return components

        components = spec.get("components")
        if not isinstance(components, list) or not components:
            raise ValueError(
                "Assembly spec needs a non-empty 'components' list or "
                "type='desk' with dimensions_mm"
            )
        return components

    @staticmethod
    def _map_assembly_constraints(
        constraints: List[Dict[str, Any]],
        name_map: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        mapped: List[Dict[str, Any]] = []
        for constraint in constraints:
            if not isinstance(constraint, dict):
                continue
            item = dict(constraint)
            for key in ("a", "b", "inner", "outer"):
                value = item.get(key)
                if isinstance(value, str) and value in name_map:
                    item[key] = name_map[value]
            if isinstance(item.get("objects"), list):
                item["objects"] = [
                    name_map.get(str(name), str(name))
                    for name in item["objects"]
                ]
            mapped.append(item)
        return mapped

    def _delete_assembly(self, name: str) -> None:
        root = bpy.data.objects.get(f"{name}_Root") or bpy.data.objects.get(name)
        if not root or "mcp_assembly_spec" not in root:
            raise ValueError(f"Assembly '{name}' not found")
        tracked = json.loads(root.get("mcp_assembly_objects", "[]"))
        for object_name in tracked:
            obj = bpy.data.objects.get(object_name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.objects.remove(root, do_unlink=True)

    def create_assembly(
        self,
        spec: Dict[str, Any],
        replace: bool = False,
    ) -> Dict[str, Any]:
        """Build a declarative assembly and validate its constraints and audit."""
        if not isinstance(spec, dict):
            raise ValueError("Assembly spec must be an object")
        name = str(spec.get("name") or spec.get("type") or "Assembly").strip()
        if not name:
            raise ValueError("Assembly spec needs a name")
        root_name = f"{name}_Root"
        existing = bpy.data.objects.get(root_name)
        if existing:
            if not replace:
                raise ValueError(
                    f"Assembly '{name}' already exists; use update_assembly or replace=True"
                )
            self._delete_assembly(name)

        components = self._assembly_component_specs(spec)
        root = bpy.data.objects.new(root_name, None)
        root.empty_display_type = "PLAIN_AXES"
        root["mcp_assembly_spec"] = json.dumps(spec)
        root["mcp_assembly_objects"] = json.dumps([])
        bpy.context.collection.objects.link(root)

        created: List[str] = []
        name_map: Dict[str, str] = {}
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                raise ValueError(f"Component {index} must be an object")
            component_name = str(component.get("name") or f"Part_{index + 1}").strip()
            if not component_name:
                raise ValueError(f"Component {index} needs a name")
            object_name = f"{name}_{component_name}"
            result = self.create_parametric_part(
                name=object_name,
                shape=str(component.get("shape", "BOX")),
                dimensions=self._component_dimensions(component),
                location=[float(value) for value in component.get("location", [0.0, 0.0, 0.0])],
                rotation_deg=[float(value) for value in component.get("rotation_deg", [0.0, 0.0, 0.0])],
                origin=str(component.get("origin", "BOTTOM")),
                bevel_width=float(component.get("bevel_width", 0.003)),
                bevel_segments=int(component.get("bevel_segments", 2)),
                subsurf_levels=int(component.get("subsurf_levels", 0)),
                taper_ratio=float(component.get("taper_ratio", 0.7)),
                thickness=float(component.get("thickness", 0.05)),
                color=component.get("color"),
                material_name=component.get("material_name"),
                parent_name=root_name,
                segments=int(component.get("segments", 32)),
            )
            actual_name = result["name"]
            created.append(actual_name)
            name_map[component_name] = actual_name

        root["mcp_assembly_objects"] = json.dumps(created)
        constraints = self._map_assembly_constraints(
            spec.get("constraints") or [], name_map
        )
        constraint_report = (
            self.validate_constraints(constraints) if constraints else None
        )
        audit = self.audit_3d_model(object_names=created)
        return {
            "success": True,
            "assembly": name,
            "root": root.name,
            "components": created,
            "component_map": name_map,
            "spec": spec,
            "constraints": constraint_report,
            "audit": audit,
            "passed": bool(audit.get("passed")) and (
                constraint_report is None or constraint_report["passed"]
            ),
        }

    def update_assembly(
        self,
        name: str,
        changes: Optional[Dict[str, Any]] = None,
        spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Rebuild an assembly from its stored spec plus a deep-merged changes patch."""
        root = bpy.data.objects.get(f"{name}_Root") or bpy.data.objects.get(name)
        if not root or "mcp_assembly_spec" not in root:
            raise ValueError(f"Assembly '{name}' not found")
        stored = json.loads(root["mcp_assembly_spec"])
        new_spec = spec if spec is not None else self._deep_merge(stored, changes or {})
        if not isinstance(new_spec, dict):
            raise ValueError("Updated assembly spec must be an object")
        new_spec["name"] = name
        self._delete_assembly(name)
        result = self.create_assembly(new_spec, replace=True)
        result["changes"] = changes or {}
        return result

    def attach_and_align(
        self,
        part_name: str,
        target_name: str,
        relation: str = "ON_TOP",
        align_x: str = "CENTER",
        align_y: str = "CENTER",
        align_z: str = "CENTER",
        inset_x: float = 0.0,
        inset_y: float = 0.0,
        inset_z: float = 0.0,
        penetration: float = 0.004,
        parent_to_target: bool = True,
    ) -> Dict[str, Any]:
        part = bpy.data.objects.get(part_name)
        target = bpy.data.objects.get(target_name)
        if not part or not target:
            raise ValueError(f"Objects '{part_name}' and '{target_name}' must exist")

        aabb_p = self._get_aabb(part)
        aabb_t = self._get_aabb(target)

        px_min, py_min, pz_min = aabb_p[0]
        px_max, py_max, pz_max = aabb_p[1]
        tx_min, ty_min, tz_min = aabb_t[0]
        tx_max, ty_max, tz_max = aabb_t[1]

        dx, dy, dz = 0.0, 0.0, 0.0
        rel_upper = relation.upper()

        if rel_upper == "ON_TOP":
            dz = (tz_max - penetration + inset_z) - pz_min
        elif rel_upper == "BELOW":
            dz = (tz_min + penetration - inset_z) - pz_max
        elif rel_upper == "FRONT":  # -Y direction
            dy = (ty_min + penetration - inset_y) - py_max
        elif rel_upper == "BACK":   # +Y direction
            dy = (ty_max - penetration + inset_y) - py_min
        elif rel_upper == "LEFT":   # -X direction
            dx = (tx_min + penetration - inset_x) - px_max
        elif rel_upper == "RIGHT":  # +X direction
            dx = (tx_max - penetration + inset_x) - px_min

        # Alignments
        if rel_upper in ("ON_TOP", "BELOW"):
            if align_x == "CENTER":
                dx = ((tx_min + tx_max) / 2.0 + inset_x) - ((px_min + px_max) / 2.0)
            elif align_x == "LEFT":
                dx = (tx_min + inset_x) - px_min
            elif align_x == "RIGHT":
                dx = (tx_max - inset_x) - px_max

            if align_y == "CENTER":
                dy = ((ty_min + ty_max) / 2.0 + inset_y) - ((py_min + py_max) / 2.0)
            elif align_y == "FRONT":
                dy = (ty_min + inset_y) - py_min
            elif align_y == "BACK":
                dy = (ty_max - inset_y) - py_max

        part.location += Vector((dx, dy, dz))
        bpy.context.view_layer.update()

        # BVH Snap refinement
        gap, snap_delta, overlap = self._compute_surface_gap_and_overlap(part, target)
        if gap > 0.0001 and gap < 0.25:
            part.location += Vector(snap_delta) * (1.0 - penetration / max(gap, 0.001))
            bpy.context.view_layer.update()

        if parent_to_target:
            part.parent = target
            part.matrix_parent_inverse = target.matrix_world.inverted()

        return {
            "success": True,
            "part": part.name,
            "target": target.name,
            "relation": rel_upper,
            "final_world_aabb": self._get_aabb(part),
            "surface_gap": gap,
            "overlap_ratio": overlap,
        }

    def snap_to_semantic_anchor(
        self,
        part_name: str,
        target_name: str,
        anchor: str = "TOP_CENTER",
        offset: Optional[List[float]] = None,
        match_dimensions_axes: Optional[List[str]] = None,
        penetration: float = 0.004,
        parent_to_target: bool = True,
    ) -> Dict[str, Any]:
        """Place part_name on target_name with human words (no math): TOP/BOTTOM/FRONT/BACK/LEFT/RIGHT centers, edges, corners."""
        part = bpy.data.objects.get(part_name)
        target = bpy.data.objects.get(target_name)
        if not part or not target:
            raise ValueError(f"Objects '{part_name}' and '{target_name}' must exist")
        if part.type != "MESH" or target.type != "MESH":
            raise TypeError("snap_to_semantic_anchor needs MESH objects")

        # Optional auto-width: match part size to target on requested axes before placing.
        for ax in [str(a).upper() for a in (match_dimensions_axes or [])]:
            if ax in ("X", "Y", "Z"):
                with suppress(Exception):
                    t_dims = Vector(target.dimensions)
                    p_dims = Vector(part.dimensions)
                    idx = {"X": 0, "Y": 1, "Z": 2}[ax]
                    if p_dims[idx] > 1e-6:
                        new_dims = [part.dimensions[i] if i != idx else t_dims[idx] for i in range(3)]
                        part.dimensions = Vector(new_dims)
                        bpy.context.view_layer.update()
                        self.repair_mesh_geometry(object_names=[part.name], apply_scale=True)

        aabb_p = self._get_aabb(part)
        aabb_t = self._get_aabb(target)
        pmin, pmax = Vector(aabb_p[0]), Vector(aabb_p[1])
        tmin, tmax = Vector(aabb_t[0]), Vector(aabb_t[1])
        pcen, tcen = (pmin + pmax) / 2.0, (tmin + tmax) / 2.0
        key = anchor.strip().upper()

        if key == "TOP_CENTER":
            d = Vector((tcen.x - pcen.x, tcen.y - pcen.y, tmax.z - penetration - pmin.z))
        elif key == "BOTTOM_CENTER":
            d = Vector((tcen.x - pcen.x, tcen.y - pcen.y, tmin.z + penetration - pmax.z))
        elif key == "FRONT_CENTER":
            d = Vector((tcen.x - pcen.x, tmin.y + penetration - pmax.y, tcen.z - pcen.z))
        elif key == "BACK_CENTER":
            d = Vector((tcen.x - pcen.x, tmax.y - penetration - pmin.y, tcen.z - pcen.z))
        elif key == "LEFT_CENTER":
            d = Vector((tmin.x + penetration - pmax.x, tcen.y - pcen.y, tcen.z - pcen.z))
        elif key == "RIGHT_CENTER":
            d = Vector((tmax.x - penetration - pmin.x, tcen.y - pcen.y, tcen.z - pcen.z))
        elif key == "TOP_FRONT_EDGE":
            d = Vector((tcen.x - pcen.x, tmin.y - pmin.y, tmax.z - penetration - pmin.z))
        elif key == "TOP_BACK_EDGE":
            d = Vector((tcen.x - pcen.x, tmax.y - pmax.y, tmax.z - penetration - pmin.z))
        elif key == "CORNER_FL":
            d = Vector((tmin.x - pmin.x, tmin.y - pmin.y, tmax.z - penetration - pmin.z))
        elif key == "CORNER_FR":
            d = Vector((tmax.x - pmax.x, tmin.y - pmin.y, tmax.z - penetration - pmin.z))
        elif key == "CORNER_BL":
            d = Vector((tmin.x - pmin.x, tmax.y - pmax.y, tmax.z - penetration - pmin.z))
        elif key == "CORNER_BR":
            d = Vector((tmax.x - pmax.x, tmax.y - pmax.y, tmax.z - penetration - pmin.z))
        elif key == "INSIDE_CENTER":
            d = Vector((tcen.x - pcen.x, tcen.y - pcen.y, tcen.z - pcen.z))
        else:
            raise ValueError(
                f"Unknown anchor '{anchor}'. Valid: TOP_CENTER, BOTTOM_CENTER, FRONT_CENTER, "
                "BACK_CENTER, LEFT_CENTER, RIGHT_CENTER, TOP_FRONT_EDGE, TOP_BACK_EDGE, "
                "CORNER_FL, CORNER_FR, CORNER_BL, CORNER_BR, INSIDE_CENTER."
            )

        off = offset or [0.0, 0.0, 0.0]
        part.location += d + Vector((float(off[0]), float(off[1]), float(off[2])))
        bpy.context.view_layer.update()

        # Same 4mm BVH weld refinement as attach_and_align.
        gap, snap_delta, overlap = self._compute_surface_gap_and_overlap(part, target)
        if 0.0001 < gap < 0.25:
            part.location += Vector(snap_delta) * (1.0 - penetration / max(gap, 0.001))
            bpy.context.view_layer.update()

        if parent_to_target:
            part.parent = target
            part.matrix_parent_inverse = target.matrix_world.inverted()

        return {
            "success": True,
            "part": part.name,
            "target": target.name,
            "anchor": key,
            "final_world_aabb": self._get_aabb(part),
            "surface_gap": gap,
            "overlap_ratio": overlap,
        }

    def list_semantic_anchors(self, object_name: str) -> Dict[str, Any]:
        """List evaluated semantic anchors for a mesh or armature."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            raise ValueError(f"Object '{object_name}' not found")
        anchors = AnchorService.for_object(obj)
        return {
            "object": obj.name,
            "type": obj.type,
            "count": len(anchors),
            "anchors": [
                {**anchor.to_dict(), "name": name}
                for name, anchor in sorted(anchors.items())
            ],
        }

    def anchor_operation(
        self,
        operation: str,
        part_name: Optional[str] = None,
        target_name: Optional[str] = None,
        part_anchor: str = "CENTER",
        target_anchor: str = "TOP_CENTER",
        offset: Optional[List[float]] = None,
        gap: float = 0.0,
        normal: Optional[List[float]] = None,
        object_names: Optional[List[str]] = None,
        axis: str = "X",
        plane: float = 0.0,
        spacing: Optional[float] = None,
        duplicate: bool = True,
        parent_to_target: bool = False,
    ) -> Dict[str, Any]:
        """Align, mate, offset, orient, distribute or mirror using semantic anchors."""
        op = str(operation).strip().lower()
        if op in ("align", "mate", "offset", "orient_normal"):
            part = bpy.data.objects.get(part_name) if part_name else None
            if not part:
                raise ValueError("part_name is required for this operation")
            if op == "offset":
                return AnchorService.offset(part, part_anchor, offset or [0.0, 0.0, 0.0])
            if op == "orient_normal":
                if not normal:
                    raise ValueError("normal is required for orient_normal")
                return AnchorService.orient_normal(part, part_anchor, normal)
            target = bpy.data.objects.get(target_name) if target_name else None
            if not target:
                raise ValueError("target_name is required for align/mate")
            if op == "align":
                return AnchorService.align(
                    part, target, part_anchor, target_anchor, offset, parent_to_target
                )
            return AnchorService.mate(
                part, target, part_anchor, target_anchor, gap, parent_to_target
            )

        objects = [
            bpy.data.objects.get(name)
            for name in (object_names or [])
        ]
        objects = [item for item in objects if item is not None]
        if op == "distribute":
            return AnchorService.distribute(objects, axis, spacing)
        if op == "mirror":
            return AnchorService.mirror(objects, axis, plane, duplicate)
        raise ValueError(
            f"Unknown anchor operation '{operation}'. Valid: align, mate, offset, "
            "orient_normal, distribute, mirror."
        )

    def validate_constraints(self, constraints: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate assembly constraints without changing the scene."""
        results: List[Dict[str, Any]] = []
        for index, constraint in enumerate(constraints or []):
            if not isinstance(constraint, dict):
                results.append({
                    "index": index,
                    "type": "unknown",
                    "passed": False,
                    "error": "constraint must be an object",
                })
                continue
            ctype = str(constraint.get("type", "")).strip().lower()
            try:
                results.append(self._evaluate_constraint(index, ctype, constraint))
            except Exception as exc:
                results.append({
                    "index": index,
                    "type": ctype,
                    "passed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        passed_count = sum(1 for result in results if result.get("passed"))
        return {
            "passed": bool(results) and passed_count == len(results),
            "count": len(results),
            "passed_count": passed_count,
            "failed_count": len(results) - passed_count,
            "results": results,
        }

    def _evaluate_constraint(
        self,
        index: int,
        ctype: str,
        constraint: Dict[str, Any],
    ) -> Dict[str, Any]:
        tolerance = float(constraint.get("tolerance", 0.001))

        def get_object(name: Any) -> bpy.types.Object:
            obj = bpy.data.objects.get(str(name)) if name else None
            if not obj:
                raise ValueError(f"Object '{name}' not found")
            return obj

        def get_anchor(
            name: Any,
            anchor: Any,
            default: str,
        ) -> SemanticAnchor:
            obj = get_object(name)
            return AnchorService.get(obj, str(anchor or default))

        def result(
            passed: bool,
            expected: Any,
            actual: Any,
            method: str,
            objects: List[str],
            details: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            return {
                "index": index,
                "type": ctype,
                "passed": bool(passed),
                "objects": objects,
                "expected": expected,
                "actual": actual,
                "tolerance": tolerance,
                "method": method,
                "details": details or {},
            }

        if ctype in (
            "mate", "align", "distance", "offset",
            "flush", "parallel", "perpendicular",
        ):
            a_name = constraint.get("a") or constraint.get("part")
            b_name = constraint.get("b") or constraint.get("target")
            part_anchor = get_anchor(a_name, constraint.get("a_anchor"), "CENTER")
            target_anchor = get_anchor(b_name, constraint.get("b_anchor"), "TOP_CENTER")
            part_position = Vector(part_anchor.position)
            target_position = Vector(target_anchor.position)
            part_normal = Vector(part_anchor.normal)
            target_normal = Vector(target_anchor.normal)
            objects = [part_anchor.object_name, target_anchor.object_name]

            if ctype == "mate":
                gap = float(constraint.get("gap", 0.0))
                expected_position = target_position + target_normal * gap
                distance = (part_position - expected_position).length
                normal_dot = part_normal.dot(-target_normal)
                passed = distance <= tolerance and normal_dot >= 0.999
                return result(
                    passed,
                    {"position": [round(float(v), 6) for v in expected_position], "normal_dot": -1.0},
                    {"position": [round(float(v), 6) for v in part_position], "normal_dot": round(float(normal_dot), 6), "distance": round(float(distance), 6)},
                    "semantic_anchor_mate",
                    objects,
                    {"details": {"gap": gap}},
                )
            if ctype == "align":
                distance = (part_position - target_position).length
                return result(
                    distance <= tolerance,
                    [round(float(v), 6) for v in target_position],
                    [round(float(v), 6) for v in part_position],
                    "semantic_anchor_align",
                    objects,
                    {"details": {"distance": round(float(distance), 6)}},
                )
            if ctype == "distance":
                expected_distance = float(constraint.get("distance", 0.0))
                actual_distance = (part_position - target_position).length
                return result(
                    abs(actual_distance - expected_distance) <= tolerance,
                    expected_distance,
                    round(float(actual_distance), 6),
                    "semantic_anchor_distance",
                    objects,
                )
            if ctype == "offset":
                offset = Vector(constraint.get("offset", (0.0, 0.0, 0.0)))
                actual_offset = part_position - target_position
                delta = (actual_offset - offset).length
                return result(
                    delta <= tolerance,
                    [round(float(v), 6) for v in offset],
                    [round(float(v), 6) for v in actual_offset],
                    "semantic_anchor_offset",
                    objects,
                    {"details": {"delta": round(float(delta), 6)}},
                )
            if ctype == "flush":
                normal_dot = abs(part_normal.dot(target_normal))
                plane_distance = abs((part_position - target_position).dot(target_normal))
                return result(
                    normal_dot >= 0.999 and plane_distance <= tolerance,
                    {"normal_dot": 1.0, "plane_distance": 0.0},
                    {"normal_dot": round(float(normal_dot), 6), "plane_distance": round(float(plane_distance), 6)},
                    "semantic_anchor_flush",
                    objects,
                )
            if ctype == "parallel":
                normal_dot = abs(part_normal.dot(target_normal))
                return result(
                    normal_dot >= 1.0 - tolerance,
                    1.0,
                    round(float(normal_dot), 6),
                    "semantic_anchor_parallel",
                    objects,
                )
            normal_dot = abs(part_normal.dot(target_normal))
            return result(
                normal_dot <= tolerance,
                0.0,
                round(float(normal_dot), 6),
                "semantic_anchor_perpendicular",
                objects,
            )

        if ctype == "center":
            names = constraint.get("objects") or [
                constraint.get("a"), constraint.get("b")
            ]
            objects = [get_object(name) for name in names if name]
            if len(objects) < 2:
                raise ValueError("center needs at least two objects")
            axes = [str(axis).upper() for axis in constraint.get("axes", ["X", "Y"])]
            snapshots = [GeometryService.snapshot(obj) for obj in objects]
            centers = [
                [
                    (snapshot.world_aabb[0][axis] + snapshot.world_aabb[1][axis]) / 2.0
                    for axis in range(3)
                ]
                for snapshot in snapshots
            ]
            deltas = []
            for center in centers[1:]:
                for axis in axes:
                    axis_index = {"X": 0, "Y": 1, "Z": 2}.get(axis)
                    if axis_index is None:
                        raise ValueError(f"Invalid center axis '{axis}'")
                    deltas.append(abs(center[axis_index] - centers[0][axis_index]))
            maximum = max(deltas) if deltas else 0.0
            return result(
                maximum <= tolerance,
                {"axes": axes, "max_delta": 0.0},
                {"axes": axes, "max_delta": round(float(maximum), 6)},
                "evaluated_aabb_center",
                [obj.name for obj in objects],
            )

        if ctype == "ground_contact":
            names = constraint.get("objects") or [constraint.get("a")]
            objects = [get_object(name) for name in names if name]
            snapshots = [GeometryService.snapshot(obj) for obj in objects]
            ground = GeometryService.ground_contact(snapshots, tolerance)
            return result(
                ground["passed"],
                0.0,
                ground["min_z"],
                ground["method"],
                [obj.name for obj in objects],
                {"details": ground},
            )

        if ctype == "symmetry":
            names = constraint.get("objects") or []
            objects = [get_object(name) for name in names if name]
            axis = str(constraint.get("axis", "X")).upper()
            plane = float(constraint.get("plane", 0.0))
            symmetry = GeometryService.symmetry_error(
                objects, axis=axis, plane=plane, tolerance=tolerance
            )
            return result(
                symmetry["passed"],
                0.0,
                symmetry["max_error"],
                symmetry["method"],
                [obj.name for obj in objects],
                {"details": symmetry},
            )

        if ctype in ("no_intersection", "surface_contact"):
            if ctype == "no_intersection":
                names = constraint.get("objects") or []
                objects = [get_object(name) for name in names if name]
                if len(objects) < 2:
                    raise ValueError("no_intersection needs at least two objects")
            else:
                objects = [
                    get_object(constraint.get("a")),
                    get_object(constraint.get("b")),
                ]
            snapshots = {
                obj.name: GeometryService.snapshot(obj) for obj in objects
            }
            graph = GeometryService.contact_graph(objects, tolerance)
            if ctype == "no_intersection":
                violations = []
                for pair in graph["pairs"]:
                    if not pair["surface_intersection"]:
                        continue
                    if not self._is_face_contact(
                        snapshots[pair["a"]].world_aabb,
                        snapshots[pair["b"]].world_aabb,
                    ):
                        violations.append(pair)
                return result(
                    not violations,
                    "no interpenetration",
                    {"violations": len(violations)},
                    "bvh_overlap_face_contact",
                    [obj.name for obj in objects],
                    {"details": {"collisions": violations}},
                )

            pair = next(
                (
                    item for item in graph["pairs"]
                    if {item["a"], item["b"]} == {objects[0].name, objects[1].name}
                ),
                None,
            )
            if pair is None:
                passed = False
                actual = {"min_distance": None}
            elif pair["surface_intersection"]:
                passed = self._is_face_contact(
                    snapshots[pair["a"]].world_aabb,
                    snapshots[pair["b"]].world_aabb,
                )
                actual = pair
            else:
                passed = pair["min_distance"] <= tolerance
                actual = pair
            return result(
                passed,
                f"surface distance <= {tolerance}",
                actual,
                "bvh_overlap_or_nearest",
                [obj.name for obj in objects],
                {"details": pair or {}},
            )

        if ctype == "inside":
            inner = get_object(constraint.get("inner") or constraint.get("a"))
            outer = get_object(constraint.get("outer") or constraint.get("b"))
            inner_snapshot = GeometryService.snapshot(inner)
            outer_snapshot = GeometryService.snapshot(outer)
            outside_vertices = 0
            maximum_excess = 0.0
            for vertex in inner_snapshot.vertices_world:
                for axis in range(3):
                    low = outer_snapshot.world_aabb[0][axis] - tolerance
                    high = outer_snapshot.world_aabb[1][axis] + tolerance
                    if vertex[axis] < low:
                        outside_vertices += 1
                        maximum_excess = max(maximum_excess, low - vertex[axis])
                    elif vertex[axis] > high:
                        outside_vertices += 1
                        maximum_excess = max(maximum_excess, vertex[axis] - high)
            return result(
                outside_vertices == 0,
                "all vertices inside the outer AABB",
                {
                    "outside_vertices": outside_vertices,
                    "max_excess": round(float(maximum_excess), 6),
                },
                "evaluated_aabb_containment",
                [inner.name, outer.name],
            )

        raise ValueError(f"Unknown constraint type '{ctype}'")

    def orient_and_face_towards(
        self,
        object_name: str,
        look_at_target: Any,
        up_axis: str = "Z",
        front_axis: str = "-Y",
    ) -> Dict[str, Any]:
        """Aim object_name at another object (or [x,y,z]) with quaternions — no Euler math for the LLM."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            raise ValueError(f"Object '{object_name}' not found")
        bpy.context.view_layer.update()

        if isinstance(look_at_target, (list, tuple)):
            target_loc = Vector((float(look_at_target[0]), float(look_at_target[1]), float(look_at_target[2])))
            target_label = str(list(look_at_target))
        else:
            tgt = bpy.data.objects.get(str(look_at_target))
            if not tgt:
                raise ValueError(f"Target '{look_at_target}' not found")
            target_loc = tgt.matrix_world.translation.copy()
            target_label = tgt.name

        direction = target_loc - obj.matrix_world.translation.copy()
        if direction.length < 1e-6:
            raise ValueError(f"Object '{object_name}' is already at the target")

        track = str(front_axis).strip().upper()
        if track not in ("X", "-X", "Y", "-Y", "Z", "-Z"):
            raise ValueError(f"front_axis must be X/-X/Y/-Y/Z/-Z (got '{front_axis}')")
        up_clean = str(up_axis).strip().upper().replace("-", "")
        if up_clean not in ("X", "Y", "Z"):
            raise ValueError(f"up_axis must be X/Y/Z (got '{up_axis}')")

        quat = direction.to_track_quat(track, up_clean)
        if obj.rotation_mode == "QUATERNION":
            if obj.parent:
                obj.rotation_quaternion = obj.parent.matrix_world.to_quaternion().inverted() @ quat
            else:
                obj.rotation_quaternion = quat
        else:
            if obj.parent:
                local_quat = obj.parent.matrix_world.to_quaternion().inverted() @ quat
                obj.rotation_euler = local_quat.to_euler()
            else:
                obj.rotation_euler = quat.to_euler()
        bpy.context.view_layer.update()

        return {
            "success": True,
            "object": obj.name,
            "target": target_label,
            "front_axis": track,
            "up_axis": up_clean,
            "rotation_euler_deg": [round(math.degrees(c), 2) for c in obj.rotation_euler]
            if obj.rotation_mode != "QUATERNION" else None,
        }

    def spawn_corner_supports(
        self,
        target_name: str,
        prefix: str = "Leg",
        shape: str = "TAPERED_CYLINDER",
        thickness: float = 0.04,
        height: Optional[float] = None,
        inset_x: float = 0.04,
        inset_y: float = 0.04,
        taper_ratio: float = 0.7,
        flare_angle_deg: float = 0.0,
        reach_ground: bool = True,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        target = bpy.data.objects.get(target_name)
        if not target:
            raise ValueError(f"Target '{target_name}' not found")
        aabb = self._get_aabb(target)
        t_min_x, t_min_y, t_min_z = aabb[0]
        t_max_x, t_max_y, _ = aabb[1]

        leg_h = t_min_z if reach_ground else (height or 0.4)
        z_base = 0.0 if reach_ground else (t_min_z - leg_h)

        positions = {
            f"{prefix}_FL": (t_min_x + inset_x, t_min_y + inset_y, -flare_angle_deg, flare_angle_deg),
            f"{prefix}_FR": (t_max_x - inset_x, t_min_y + inset_y, flare_angle_deg, flare_angle_deg),
            f"{prefix}_BL": (t_min_x + inset_x, t_max_y - inset_y, -flare_angle_deg, -flare_angle_deg),
            f"{prefix}_BR": (t_max_x - inset_x, t_max_y - inset_y, flare_angle_deg, -flare_angle_deg),
        }

        created = []
        for leg_name, (x, y, rot_y, rot_x) in positions.items():
            res = self.create_parametric_part(
                name=leg_name,
                shape=shape,
                dimensions=[thickness, thickness, leg_h + 0.005],
                location=[x, y, z_base],
                rotation_deg=[rot_x, rot_y, 0.0],
                origin="BOTTOM",
                taper_ratio=taper_ratio,
                parent_name=target_name,
                color=color,
                material_name=material_name,
            )
            created.append(res["name"])

        return {"success": True, "target": target_name, "supports": created, "height": leg_h}

    def symmetry_mirror(
        self,
        object_name: str,
        target_reference: Optional[str] = None,
        axis: str = "X",
        mode: str = "DUPLICATE",
        new_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        src = bpy.data.objects.get(object_name)
        if not src:
            raise ValueError(f"Object '{object_name}' not found")

        ref_obj = bpy.data.objects.get(target_reference) if target_reference else None
        center = ref_obj.location if ref_obj else Vector((0, 0, 0))

        axis_upper = axis.upper()
        scale_vec = Vector((-1 if axis_upper == "X" else 1, -1 if axis_upper == "Y" else 1, -1 if axis_upper == "Z" else 1))

        if mode.upper() == "MODIFIER":
            mod = src.modifiers.new(name="Symmetry_Mirror", type="MIRROR")
            mod.use_axis[0] = (axis_upper == "X")
            mod.use_axis[1] = (axis_upper == "Y")
            mod.use_axis[2] = (axis_upper == "Z")
            if ref_obj:
                mod.mirror_object = ref_obj
            return {"success": True, "object": src.name, "mode": "MODIFIER"}

        # DUPLICATE mode
        dest_name = new_name or (
            src.name.replace("_L", "_R") if "_L" in src.name else f"{src.name}_Mirrored_{axis_upper}"
        )
        dup_mesh = src.data.copy()
        dup_obj = bpy.data.objects.new(dest_name, dup_mesh)
        bpy.context.collection.objects.link(dup_obj)

        mat = src.matrix_world.copy()
        mirr_mat = Matrix.Translation(center) @ Matrix.Diagonal((*scale_vec, 1.0)) @ Matrix.Translation(-center)
        dup_obj.matrix_world = mirr_mat @ mat

        # Flip inverted normals
        bm = bmesh.new()
        bm.from_mesh(dup_mesh)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(dup_mesh)
        bm.free()

        if src.parent:
            dup_obj.parent = src.parent
            dup_obj.matrix_parent_inverse = src.parent.matrix_world.inverted()

        return {"success": True, "source": src.name, "mirrored": dup_obj.name, "axis": axis_upper}

    def radial_array(
        self,
        object_name: str,
        count: int = 4,
        center: Optional[List[float]] = None,
        axis: str = "Z",
    ) -> Dict[str, Any]:
        src = bpy.data.objects.get(object_name)
        if not src:
            raise ValueError(f"Object '{object_name}' not found")
        cnt = max(2, int(count))
        cent = Vector(center) if center else Vector((0, 0, 0))
        axis_upper = axis.upper()
        rot_axis = Vector((1 if axis_upper == "X" else 0, 1 if axis_upper == "Y" else 0, 1 if axis_upper == "Z" else 0))

        step_angle = 2.0 * math.pi / cnt
        created = [src.name]

        for i in range(1, cnt):
            ang = i * step_angle
            dup_mesh = src.data.copy()
            dup_obj = bpy.data.objects.new(f"{src.name}_Rad_{i}", dup_mesh)
            bpy.context.collection.objects.link(dup_obj)

            rot_mat = Matrix.Translation(cent) @ Matrix.Rotation(ang, 4, rot_axis) @ Matrix.Translation(-cent)
            dup_obj.matrix_world = rot_mat @ src.matrix_world

            if src.parent:
                dup_obj.parent = src.parent
                dup_obj.matrix_parent_inverse = src.parent.matrix_world.inverted()
            created.append(dup_obj.name)

        return {"success": True, "base": src.name, "count": cnt, "instances": created}

    def boolean_operation(
        self,
        target_name: str,
        cutter_name: str,
        operation: str = "DIFFERENCE",
        apply_modifier: bool = True,
        delete_cutter: bool = True,
    ) -> Dict[str, Any]:
        target = bpy.data.objects.get(target_name)
        cutter = bpy.data.objects.get(cutter_name)
        if not target or not cutter:
            raise ValueError(f"Target '{target_name}' or Cutter '{cutter_name}' missing")

        mod = target.modifiers.new(name="BooleanOp", type="BOOLEAN")
        mod.operation = operation.upper()
        mod.object = cutter
        mod.solver = "EXACT"

        if apply_modifier:
            bpy.context.view_layer.objects.active = target
            bpy.ops.object.modifier_apply(modifier=mod.name)
            if delete_cutter:
                bpy.data.objects.remove(cutter, do_unlink=True)
            self._auto_box_uv_unwrap(target.data)
            return {"success": True, "target": target.name, "operation": operation.upper(), "applied": True}

        return {"success": True, "target": target.name, "operation": operation.upper(), "applied": False}

    def create_articulation_joint(
        self,
        parent_name: str,
        child_name: str,
        joint_location: Optional[List[float]] = None,
        rotation_limits_deg: Optional[Dict[str, List[float]]] = None,
    ) -> Dict[str, Any]:
        parent = bpy.data.objects.get(parent_name)
        child = bpy.data.objects.get(child_name)
        if not parent or not child:
            raise ValueError(f"Objects '{parent_name}' and '{child_name}' must exist")

        empty = bpy.data.objects.new(f"Joint_{parent.name}_{child.name}", None)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 0.08
        bpy.context.collection.objects.link(empty)

        if joint_location:
            empty.location = Vector(joint_location)
        else:
            _, delta, _ = self._compute_surface_gap_and_overlap(parent, child)
            empty.location = child.location + Vector(delta) / 2.0

        empty.parent = parent
        empty.matrix_parent_inverse = parent.matrix_world.inverted()

        child.parent = empty
        child.matrix_parent_inverse = empty.matrix_world.inverted()

        if rotation_limits_deg:
            con = child.constraints.new(type="LIMIT_ROTATION")
            for ax in ("x", "y", "z"):
                if ax in rotation_limits_deg:
                    lim = rotation_limits_deg[ax]
                    setattr(con, f"use_limit_{ax}", True)
                    setattr(con, f"min_{ax}", math.radians(lim[0]))
                    setattr(con, f"max_{ax}", math.radians(lim[1]))

        return {"success": True, "joint": empty.name, "parent": parent.name, "child": child.name}

    # ==========================================================================
    # 3. CURVATURE, LATHE, SWEEP, LOFT & DEFORMERS
    # ==========================================================================
    def create_lathe_part(
        self,
        name: str,
        profile_points_2d: List[List[float]],
        location: List[float] = [0.0, 0.0, 0.0],
        segments: int = 32,
        angle_deg: float = 360.0,
        bevel_width: float = 0.002,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
        parent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crea sólidos de revolución (jarrones, botellas, copas, llantas, columnas) girando un perfil 2D en Z."""
        if len(profile_points_2d) < 2:
            raise ValueError("profile_points_2d must contain at least 2 points [[r, z], ...]")

        mesh = bpy.data.meshes.new(name=f"{name}_Mesh")
        bm = bmesh.new()

        bm_verts = [bm.verts.new((float(pt[0]), 0.0, float(pt[1]))) for pt in profile_points_2d]
        bm.verts.ensure_lookup_table()
        bm_edges = [bm.edges.new((bm_verts[i], bm_verts[i + 1])) for i in range(len(bm_verts) - 1)]
        bm.edges.ensure_lookup_table()

        use_merge = (abs(angle_deg - 360.0) < 1e-3)
        bmesh.ops.spin(
            bm, geom=bm_verts + bm_edges, cent=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
            angle=math.radians(float(angle_deg)), steps=int(segments), use_merge=use_merge
        )

        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh, location=location, rotation_deg=[0, 0, 0],
            origin_mode="BOTTOM", parent_name=parent_name, color=color, material_name=material_name
        )

        if bevel_width > 0.0005:
            bev = obj.modifiers.new(name="Bevel", type="BEVEL")
            bev.width = bevel_width
            bev.segments = 2
            bev.angle_limit = math.radians(40.0)

        return {"success": True, "name": obj.name, "world_aabb": self._get_aabb(obj)}

    def create_curve_sweep(
        self,
        name: str,
        path_points_3d: List[List[float]],
        radius: float = 0.03,
        taper_end_ratio: float = 1.0,
        resolution_u: int = 12,
        bevel_resolution: int = 8,
        closed: bool = False,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
        parent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Genera tuberías, cables, cuernos, ramas o pasamanos extruyendo una curva 3D con radio y ahusamiento."""
        if len(path_points_3d) < 2:
            raise ValueError("path_points_3d must have at least 2 points [[x,y,z], ...]")

        curve_data = bpy.data.curves.new(name=f"{name}_Curve", type="CURVE")
        curve_data.dimensions = "3D"
        curve_data.bevel_depth = float(radius)
        curve_data.bevel_resolution = int(bevel_resolution)
        curve_data.resolution_u = int(resolution_u)
        curve_data.fill_mode = "FULL"

        spline = curve_data.splines.new("BEZIER")
        spline.bezier_points.add(len(path_points_3d) - 1)
        spline.use_cyclic_u = bool(closed)
        n_pts = len(path_points_3d)

        for i, pt in enumerate(path_points_3d):
            bp = spline.bezier_points[i]
            bp.co = Vector((float(pt[0]), float(pt[1]), float(pt[2])))
            bp.handle_left_type = "AUTO"
            bp.handle_right_type = "AUTO"
            t = i / max(1, n_pts - 1)
            bp.radius = 1.0 - (1.0 - float(taper_end_ratio)) * t

        temp_obj = bpy.data.objects.new(f"{name}_Temp", curve_data)
        bpy.context.collection.objects.link(temp_obj)
        bpy.context.view_layer.update()

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = temp_obj.evaluated_get(depsgraph)
        mesh_data = bpy.data.meshes.new_from_object(eval_obj)

        bpy.data.objects.remove(temp_obj, do_unlink=True)
        bpy.data.curves.remove(curve_data)

        # Cap open ends
        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh_data)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh_data, location=[0, 0, 0], rotation_deg=[0, 0, 0],
            origin_mode="CENTER", parent_name=parent_name, color=color, material_name=material_name
        )

        return {"success": True, "name": obj.name, "world_aabb": self._get_aabb(obj)}

    def create_loft_surface(
        self,
        name: str,
        cross_sections: List[List[List[float]]],
        closed_caps: bool = True,
        subsurf_levels: int = 1,
        smooth_shading: bool = True,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
        parent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Une una secuencia de secciones transversales 3D para modelar carrocerías, fuselajes o cojines ergonómicos."""
        if len(cross_sections) < 2:
            raise ValueError("cross_sections must contain at least 2 cross sections")

        # Remuestrear secciones para que todas compartan el número máximo de puntos
        max_pts = max(len(s) for s in cross_sections)
        resampled_sections = []
        for s in cross_sections:
            if len(s) == max_pts:
                resampled_sections.append(s)
            else:
                # Interpolación perimetral uniforme
                cum_len = [0.0]
                for i in range(len(s) - 1):
                    cum_len.append(cum_len[-1] + (Vector(s[i+1]) - Vector(s[i])).length)
                tot = cum_len[-1]
                new_s = []
                for k in range(max_pts):
                    target_d = (k / (max_pts - 1)) * tot
                    idx = 0
                    while idx < len(cum_len) - 1 and cum_len[idx+1] < target_d:
                        idx += 1
                    t = (target_d - cum_len[idx]) / max(1e-5, cum_len[idx+1] - cum_len[idx])
                    interp = Vector(s[idx]).lerp(Vector(s[idx+1]), t)
                    new_s.append([interp.x, interp.y, interp.z])
                resampled_sections.append(new_s)

        mesh = bpy.data.meshes.new(name=f"{name}_Mesh")
        bm = bmesh.new()

        layers_verts = []
        for sec in resampled_sections:
            v_layer = [bm.verts.new(pt) for pt in sec]
            layers_verts.append(v_layer)
        bm.verts.ensure_lookup_table()

        k = max_pts
        for s_idx in range(len(resampled_sections) - 1):
            curr_v = layers_verts[s_idx]
            next_v = layers_verts[s_idx + 1]
            for j in range(k - 1):
                bm.faces.new((curr_v[j], next_v[j], next_v[j + 1], curr_v[j + 1]))
            # Cierre perimetral si el primer y último punto coinciden o forman anillo
            if (Vector(curr_v[0].co) - Vector(curr_v[-1].co)).length < 1e-4:
                bm.faces.new((curr_v[-1], next_v[-1], next_v[0], curr_v[0]))

        if closed_caps:
            with suppress(Exception):
                bm.faces.new(reversed(layers_verts[0]))
            with suppress(Exception):
                bm.faces.new(layers_verts[-1])

        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        if smooth_shading:
            for f in bm.faces:
                f.smooth = True

        bm.to_mesh(mesh)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh, location=[0, 0, 0], rotation_deg=[0, 0, 0],
            origin_mode="CENTER", parent_name=parent_name, color=color, material_name=material_name
        )

        if subsurf_levels > 0:
            sub = obj.modifiers.new(name="Subsurf", type="SUBSURFACE")
            sub.levels = subsurf_levels

        return {"success": True, "name": obj.name, "world_aabb": self._get_aabb(obj)}

    def deform_object(
        self,
        name: str,
        deform_type: str = "BEND",
        axis: str = "Z",
        angle_deg: float = 30.0,
        factor: float = 0.5,
        apply_modifier: bool = True,
    ) -> Dict[str, Any]:
        """Aplica curvaturas (BEND), torsiones (TWIST), ahusamientos (TAPER) o estiramientos (STRETCH) controlados."""
        obj = bpy.data.objects.get(name)
        if not obj or obj.type != "MESH":
            raise ValueError(f"Object '{name}' must be an existing MESH")

        # Empty temporal como pivote de deformación central
        empty = bpy.data.objects.new(f"{name}_DeformGizmo", None)
        bpy.context.collection.objects.link(empty)
        empty.location = obj.location
        empty.rotation_euler = obj.rotation_euler

        mod = obj.modifiers.new(name=f"Deform_{deform_type}", type="SIMPLE_DEFORM")
        mod.deform_method = deform_type.upper()
        mod.deform_axis = axis.upper()
        mod.angle = math.radians(float(angle_deg))
        mod.factor = float(factor)
        mod.origin = empty

        if apply_modifier:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
            bpy.data.objects.remove(empty, do_unlink=True)
            self.repair_mesh_geometry(object_names=[obj.name], apply_scale=False)
            return {"success": True, "object": obj.name, "deform_applied": deform_type.upper()}

        return {"success": True, "object": obj.name, "modifier": mod.name, "gizmo": empty.name}

    # ==========================================================================
    # 4. ORGANIC MODELING, SKINNING & RIGGING
    # ==========================================================================
    def fuse_organic_parts(
        self,
        object_names: List[str],
        merged_name: str = "Organic_Body",
        voxel_size: float = 0.015,
        smooth_iterations: int = 5,
        smooth_factor: float = 0.5,
        keep_originals: bool = False,
    ) -> Dict[str, Any]:
        """Fusiona múltiples partes anatómicas o extremidades en una piel continua sin costuras usando Voxel Remesh."""
        targets = [bpy.data.objects.get(n) for n in object_names if bpy.data.objects.get(n) and bpy.data.objects.get(n).type == "MESH"]
        if not targets:
            raise ValueError("No valid MESH objects found to fuse")

        # Unificar mediante BMesh en espacio mundial
        bm_fused = bmesh.new()
        for t in targets:
            bm_temp = bmesh.new()
            bm_temp.from_mesh(t.data)
            bm_temp.transform(t.matrix_world)
            for f in bm_temp.faces:
                bm_fused.faces.new([bm_fused.verts.new(v.co) for v in f.verts])
            bm_temp.free()

        fused_mesh = bpy.data.meshes.new(f"{merged_name}_Mesh")
        bm_fused.to_mesh(fused_mesh)
        bm_fused.free()

        fused_obj = bpy.data.objects.new(merged_name, fused_mesh)
        bpy.context.collection.objects.link(fused_obj)
        bpy.context.view_layer.objects.active = fused_obj

        # 1. Remesh Voxel para fundir las uniones
        remesh = fused_obj.modifiers.new(name="VoxelRemesh", type="REMESH")
        remesh.mode = "VOXEL"
        remesh.voxel_size = max(0.005, float(voxel_size))
        remesh.adaptivity = 0.0
        remesh.use_smooth_shade = True
        bpy.ops.object.modifier_apply(modifier=remesh.name)

        # 2. Suavizado correctivo orgánico
        smooth = fused_obj.modifiers.new(name="OrganicSmooth", type="CORRECTIVE_SMOOTH")
        smooth.iterations = int(smooth_iterations)
        smooth.factor = float(smooth_factor)
        smooth.smooth_type = "LENGTH_WEIGHTED"
        bpy.ops.object.modifier_apply(modifier=smooth.name)

        self._auto_box_uv_unwrap(fused_mesh)

        if not keep_originals:
            for t in targets:
                bpy.data.objects.remove(t, do_unlink=True)

        return {"success": True, "merged_object": fused_obj.name, "world_aabb": self._get_aabb(fused_obj)}

    def create_skeleton_skin_mesh(
        self,
        name: str,
        nodes_dict: Dict[str, List[float]],
        edges_list: List[List[str]],
        radii_dict: Dict[str, Any],
        subsurf_levels: int = 2,
        voxel_remesh_size: float = 0.0,
        color: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Construye cuerpos orgánicos, criaturas ramificadas o troncos en 1 llamada usando el modificador Skin."""
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        bm = bmesh.new()

        vert_map = {}
        for node_key, coords in nodes_dict.items():
            vert_map[node_key] = bm.verts.new((float(coords[0]), float(coords[1]), float(coords[2])))
        bm.verts.ensure_lookup_table()

        for edge_pair in edges_list:
            n1, n2 = edge_pair[0], edge_pair[1]
            if n1 in vert_map and n2 in vert_map:
                bm.edges.new((vert_map[n1], vert_map[n2]))

        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj

        skin_mod = obj.modifiers.new(name="Skin", type="SKIN")
        bpy.context.view_layer.update()

        # Configurar radios en la capa de datos de vértices de piel
        skin_verts = mesh.skin_vertices[0].data if mesh.skin_vertices else None
        if skin_verts:
            for node_name, v_bm in vert_map.items():
                r = radii_dict.get(node_name, [0.06, 0.06])
                rx, ry = (r, r) if isinstance(r, (int, float)) else (r[0], r[1])
                skin_verts[v_bm.index].radius = (float(rx), float(ry))
            skin_verts[0].use_root = True

        if subsurf_levels > 0:
            sub = obj.modifiers.new(name="Subsurf", type="SUBSURFACE")
            sub.levels = subsurf_levels

        if voxel_remesh_size > 0.005:
            # Evaluar y hornear en malla uniforme
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)
            new_mesh = bpy.data.meshes.new_from_object(eval_obj)
            obj.modifiers.clear()
            obj.data = new_mesh
            remesh = obj.modifiers.new(name="VoxelRemesh", type="REMESH")
            remesh.mode = "VOXEL"
            remesh.voxel_size = voxel_remesh_size
            remesh.use_smooth_shade = True
            bpy.ops.object.modifier_apply(modifier=remesh.name)

        self._auto_box_uv_unwrap(obj.data)
        if color:
            self.create_material(f"Mat_{name}", color=color)
            self.assign_material(name, f"Mat_{name}")

        return {"success": True, "name": obj.name, "world_aabb": self._get_aabb(obj)}

    def auto_rig_humanoid(
        self,
        mesh_name: str,
        armature_name: str = "Humanoid_Rig",
        bind_automatic_weights: bool = True,
    ) -> Dict[str, Any]:
        """Genera un esqueleto de deformación humanoide simétrico proporcional y lo enlaza automáticamente a la malla."""
        mesh_obj = bpy.data.objects.get(mesh_name)
        if not mesh_obj or mesh_obj.type != "MESH":
            raise ValueError(f"Mesh object '{mesh_name}' not found")

        aabb = self._get_aabb(mesh_obj)
        min_c, max_c = Vector(aabb[0]), Vector(aabb[1])
        height = max_c.z - min_c.z
        width = max_c.x - min_c.x
        depth = max_c.y - min_c.y
        cx = (min_c.x + max_c.x) / 2.0
        cy = (min_c.y + max_c.y) / 2.0
        base_z = min_c.z

        arm_data = bpy.data.armatures.new(f"{armature_name}_Data")
        arm_obj = bpy.data.objects.new(armature_name, arm_data)
        bpy.context.collection.objects.link(arm_obj)
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = arm_data.edit_bones

        def make_bone(bname, head, tail, parent_bone=None):
            b = edit_bones.new(bname)
            b.head = Vector(head)
            b.tail = Vector(tail)
            if parent_bone:
                b.parent = parent_bone
                b.use_connect = False
            return b

        # Landmarks
        z_pelvis = base_z + height * 0.52
        z_spine = base_z + height * 0.65
        z_chest = base_z + height * 0.77
        z_neck = base_z + height * 0.86
        z_head = base_z + height * 0.98

        b_hips = make_bone("Hips", (cx, cy, z_pelvis), (cx, cy, z_spine))
        b_spine = make_bone("Spine", (cx, cy, z_spine), (cx, cy, z_chest), b_hips)
        b_chest = make_bone("Chest", (cx, cy, z_chest), (cx, cy, z_neck), b_spine)
        b_neck = make_bone("Neck", (cx, cy, z_neck), (cx, cy, (z_neck + z_head) / 2.0), b_chest)
        b_head = make_bone("Head", (cx, cy, (z_neck + z_head) / 2.0), (cx, cy, z_head), b_neck)

        # Extremidades bilaterales
        shoulder_w = width * 0.38
        arm_span = width * 0.48
        z_elbow = base_z + height * 0.62
        z_wrist = base_z + height * 0.48
        z_hand = base_z + height * 0.42

        hip_w = width * 0.16
        z_knee = base_z + height * 0.28
        z_ankle = base_z + height * 0.06
        toe_y = cy - depth * 0.25

        for side, sign in (("_L", 1.0), ("_R", -1.0)):
            # Brazo
            b_sh = make_bone(f"Shoulder{side}", (cx, cy, z_chest), (cx + sign * shoulder_w, cy, z_chest), b_chest)
            b_uarm = make_bone(f"UpperArm{side}", (cx + sign * shoulder_w, cy, z_chest), (cx + sign * arm_span, cy, z_elbow), b_sh)
            b_larm = make_bone(f"LowerArm{side}", (cx + sign * arm_span, cy, z_elbow), (cx + sign * arm_span, cy, z_wrist), b_uarm)
            b_hand = make_bone(f"Hand{side}", (cx + sign * arm_span, cy, z_wrist), (cx + sign * arm_span, cy, z_hand), b_larm)
            # Pierna
            b_uleg = make_bone(f"UpperLeg{side}", (cx + sign * hip_w, cy, z_pelvis), (cx + sign * hip_w, cy, z_knee), b_hips)
            b_lleg = make_bone(f"LowerLeg{side}", (cx + sign * hip_w, cy, z_knee), (cx + sign * hip_w, cy, z_ankle), b_uleg)
            b_foot = make_bone(f"Foot{side}", (cx + sign * hip_w, cy, z_ankle), (cx + sign * hip_w, toe_y, base_z), b_lleg)

        bpy.ops.object.mode_set(mode="OBJECT")

        if bind_automatic_weights:
            bpy.ops.object.select_all(action="DESELECT")
            mesh_obj.select_set(True)
            arm_obj.select_set(True)
            bpy.context.view_layer.objects.active = arm_obj
            with suppress(Exception):
                bpy.ops.object.parent_set(type="ARMATURE_AUTO")

        return {"success": True, "armature": arm_obj.name, "target_mesh": mesh_obj.name, "weights_bound": bind_automatic_weights}

    # ==========================================================================
    # 5. PARAMETRIC ARCHITECTURE & BUILDINGS
    # ==========================================================================
    def create_floorplan_walls(
        self,
        name: str = "House_Walls",
        wall_segments: Optional[List[List[float]]] = None,
        height: float = 2.7,
        thickness: float = 0.15,
        color: Optional[List[float]] = None,
        material_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Genera muros arquitectónicos extruidos desde un plano 2D ([[x1,y1, x2,y2], ...]) soldados en Z=0.0."""
        segments = wall_segments or [[0, 0, 6, 0], [6, 0, 6, 8], [6, 8, 0, 8], [0, 8, 0, 0]]
        h = float(height)
        th = float(thickness)

        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        bm = bmesh.new()

        for seg in segments:
            x1, y1, x2, y2 = float(seg[0]), float(seg[1]), float(seg[2]), float(seg[3])
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-4:
                continue
            nx = -dy / length * (th / 2.0)
            ny = dx / length * (th / 2.0)

            # 4 vértices base y 4 superiores
            v0 = bm.verts.new((x1 - nx, y1 - ny, 0.0))
            v1 = bm.verts.new((x2 - nx, y2 - ny, 0.0))
            v2 = bm.verts.new((x2 + nx, y2 + ny, 0.0))
            v3 = bm.verts.new((x1 + nx, y1 + ny, 0.0))

            v4 = bm.verts.new((x1 - nx, y1 - ny, h))
            v5 = bm.verts.new((x2 - nx, y2 - ny, h))
            v6 = bm.verts.new((x2 + nx, y2 + ny, h))
            v7 = bm.verts.new((x1 + nx, y1 + ny, h))

            bm.faces.new((v0, v1, v2, v3))
            bm.faces.new((v7, v6, v5, v4))
            bm.faces.new((v0, v4, v5, v1))
            bm.faces.new((v1, v5, v6, v2))
            bm.faces.new((v2, v6, v7, v3))
            bm.faces.new((v3, v7, v4, v0))

        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.01)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh, location=[0, 0, 0], rotation_deg=[0, 0, 0],
            origin_mode="BOTTOM", color=color or [0.9, 0.88, 0.85, 1.0], material_name=material_name
        )

        return {"success": True, "name": obj.name, "world_aabb": self._get_aabb(obj)}

    def cut_wall_opening(
        self,
        wall_name: str,
        offset_along_wall: float = 1.0,
        sill_height: float = 0.0,
        width: float = 0.9,
        height: float = 2.1,
        opening_type: str = "DOOR",
        add_frame: bool = True,
        add_glass_or_panel: bool = True,
        frame_color: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Perfora vanos de puertas o ventanas con booleana exacta y crea marcos y hojas/cristales hijos."""
        wall = bpy.data.objects.get(wall_name)
        if not wall:
            raise ValueError(f"Wall '{wall_name}' not found")

        aabb = self._get_aabb(wall)
        w_min, w_max = Vector(aabb[0]), Vector(aabb[1])
        dim_x = w_max.x - w_min.x
        dim_y = w_max.y - w_min.y

        # Detectar orientación del muro
        is_x_aligned = (dim_x >= dim_y)
        w_cut = float(width)
        h_cut = float(height)

        if is_x_aligned:
            cut_cx = w_min.x + offset_along_wall + w_cut / 2.0
            cut_cy = (w_min.y + w_max.y) / 2.0
            cut_dims = [w_cut, dim_y * 2.5, h_cut]
        else:
            cut_cx = (w_min.x + w_max.x) / 2.0
            cut_cy = w_min.y + offset_along_wall + w_cut / 2.0
            cut_dims = [dim_x * 2.5, w_cut, h_cut]

        cut_cz = w_min.z + sill_height + h_cut / 2.0

        # Cortador booleano
        cutter_res = self.create_parametric_part(
            name=f"_Cutter_{opening_type}",
            shape="BOX",
            dimensions=cut_dims,
            location=[cut_cx, cut_cy, cut_cz],
            origin="CENTER"
        )
        self.boolean_operation(target_name=wall_name, cutter_name=cutter_res["name"], operation="DIFFERENCE", apply_modifier=True)

        created_elements = []
        # Marco perimetral
        if add_frame:
            fr_thick = 0.05
            fr_name = f"{wall_name}_{opening_type}_Frame"
            fr_res = self.create_parametric_part(
                name=fr_name,
                shape="BOX",
                dimensions=[w_cut if is_x_aligned else 0.12, 0.12 if is_x_aligned else w_cut, h_cut],
                location=[cut_cx, cut_cy, cut_cz],
                origin="CENTER",
                parent_name=wall_name,
                color=frame_color or [0.2, 0.2, 0.2, 1.0]
            )
            created_elements.append(fr_res["name"])

        # Panel de puerta o Vidrio de ventana
        if add_glass_or_panel:
            sub_name = f"{wall_name}_{opening_type}_Leaf"
            if opening_type.upper() == "WINDOW":
                mat_glass = "Glass_PBR"
                self.create_material(mat_glass, color=[0.8, 0.9, 0.95, 1.0], roughness=0.05, alpha=0.3)
                p_res = self.create_parametric_part(
                    name=sub_name,
                    shape="BOX",
                    dimensions=[w_cut - 0.08 if is_x_aligned else 0.02, 0.02 if is_x_aligned else w_cut - 0.08, h_cut - 0.08],
                    location=[cut_cx, cut_cy, cut_cz],
                    origin="CENTER",
                    parent_name=wall_name,
                    material_name=mat_glass
                )
            else:
                p_res = self.create_parametric_part(
                    name=sub_name,
                    shape="BOX",
                    dimensions=[w_cut - 0.06 if is_x_aligned else 0.04, 0.04 if is_x_aligned else w_cut - 0.06, h_cut - 0.04],
                    location=[cut_cx, cut_cy, cut_cz],
                    origin="CENTER",
                    parent_name=wall_name,
                    color=[0.45, 0.25, 0.1, 1.0]
                )
            created_elements.append(p_res["name"])

        return {"success": True, "wall": wall_name, "opening": opening_type, "created_parts": created_elements}

    def create_parametric_roof(
        self,
        target_name: str,
        name: str = "Roof",
        style: str = "GABLE",
        pitch_deg: float = 30.0,
        overhang: float = 0.25,
        thickness: float = 0.12,
        color: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Genera techos paramétricos (GABLE a 2 aguas, HIP a 4 aguas, SHED a 1 agua o FLAT) soldados al AABB del objetivo."""
        target = bpy.data.objects.get(target_name)
        if not target:
            raise ValueError(f"Target '{target_name}' not found")

        aabb = self._get_aabb(target)
        x0, y0 = aabb[0][0] - overhang, aabb[0][1] - overhang
        x1, y1 = aabb[1][0] + overhang, aabb[1][1] + overhang
        z_base = aabb[1][2] - 0.005  # Soldadura milimétrica
        dx = x1 - x0
        dy = y1 - y0
        rise = (dx / 2.0) * math.tan(math.radians(float(pitch_deg)))
        z_peak = z_base + rise

        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        bm = bmesh.new()

        st = style.upper()
        if st == "GABLE":
            # Techo a dos aguas con cumbrera a lo largo del eje Y
            xc = (x0 + x1) / 2.0
            v_l1 = bm.verts.new((x0, y0, z_base))
            v_l2 = bm.verts.new((x0, y1, z_base))
            v_r1 = bm.verts.new((x1, y0, z_base))
            v_r2 = bm.verts.new((x1, y1, z_base))
            v_c1 = bm.verts.new((xc, y0, z_peak))
            v_c2 = bm.verts.new((xc, y1, z_peak))

            bm.faces.new((v_l1, v_l2, v_c2, v_c1))  # Vertiente Izquierda
            bm.faces.new((v_r2, v_r1, v_c1, v_c2))  # Vertiente Derecha
            bm.faces.new((v_l1, v_c1, v_r1))        # Frontis frontal
            bm.faces.new((v_r2, v_c2, v_l2))        # Frontis posterior
        elif st == "HIP":
            # Techo a 4 aguas
            xc, yc = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            v0 = bm.verts.new((x0, y0, z_base))
            v1 = bm.verts.new((x1, y0, z_base))
            v2 = bm.verts.new((x1, y1, z_base))
            v3 = bm.verts.new((x0, y1, z_base))
            v_apex = bm.verts.new((xc, yc, z_peak))
            bm.faces.new((v0, v1, v_apex))
            bm.faces.new((v1, v2, v_apex))
            bm.faces.new((v2, v3, v_apex))
            bm.faces.new((v3, v0, v_apex))
        elif st == "SHED":
            # 1 sola vertiente
            v0 = bm.verts.new((x0, y0, z_base))
            v1 = bm.verts.new((x1, y0, z_peak))
            v2 = bm.verts.new((x1, y1, z_peak))
            v3 = bm.verts.new((x0, y1, z_base))
            bm.faces.new((v0, v1, v2, v3))
        else:  # FLAT con parapeto perimetral
            v0 = bm.verts.new((x0, y0, z_base))
            v1 = bm.verts.new((x1, y0, z_base))
            v2 = bm.verts.new((x1, y1, z_base))
            v3 = bm.verts.new((x0, y1, z_base))
            bm.faces.new((v0, v1, v2, v3))

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh, location=[0, 0, 0], rotation_deg=[0, 0, 0],
            origin_mode="BOTTOM", parent_name=target_name, color=color or [0.65, 0.25, 0.18, 1.0]
        )

        # Modificador Solidify para darle masa
        sol = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
        sol.thickness = float(thickness)
        sol.offset = 1.0

        return {"success": True, "name": obj.name, "roof_style": st, "world_aabb": self._get_aabb(obj)}

    def create_staircase(
        self,
        name: str = "Staircase",
        start_location: List[float] = [0.0, 0.0, 0.0],
        width: float = 1.0,
        total_height: float = 2.7,
        total_run: float = 3.0,
        step_count: int = 15,
        style: str = "CLOSED",
        direction_deg: float = 0.0,
        handrails: bool = True,
        color: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Crea escaleras paramétricas con peldaños sólidos (CLOSED) o abiertos (OPEN) y barandillas laterales."""
        steps = max(2, int(step_count))
        dh = float(total_height) / steps
        dy = float(total_run) / steps
        w = float(width)

        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        bm = bmesh.new()

        for i in range(steps):
            y_start = i * dy
            y_end = (i + 1) * dy
            z_top = (i + 1) * dh
            z_bot = 0.0 if style.upper() == "CLOSED" else (z_top - 0.04)

            # Peldaño rectangular
            v0 = bm.verts.new((-w / 2.0, y_start, z_bot))
            v1 = bm.verts.new((w / 2.0, y_start, z_bot))
            v2 = bm.verts.new((w / 2.0, y_end, z_bot))
            v3 = bm.verts.new((-w / 2.0, y_end, z_bot))

            v4 = bm.verts.new((-w / 2.0, y_start, z_top))
            v5 = bm.verts.new((w / 2.0, y_start, z_top))
            v6 = bm.verts.new((w / 2.0, y_end, z_top))
            v7 = bm.verts.new((-w / 2.0, y_end, z_top))

            bm.faces.new((v0, v1, v2, v3))
            bm.faces.new((v7, v6, v5, v4))
            bm.faces.new((v0, v4, v5, v1))
            bm.faces.new((v1, v5, v6, v2))
            bm.faces.new((v2, v6, v7, v3))
            bm.faces.new((v3, v7, v4, v0))

        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.001)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        obj = self._create_or_reuse_mesh_object(
            name=name, mesh=mesh, location=start_location, rotation_deg=[0, 0, direction_deg],
            origin_mode="BOTTOM", color=color or [0.75, 0.75, 0.75, 1.0]
        )

        # Barandillas opcionales a ambos lados
        if handrails:
            rail_h = 0.90
            rail_l = [
                [-w / 2.0 + 0.03, 0.0, rail_h],
                [-w / 2.0 + 0.03, total_run, total_height + rail_h],
            ]
            rail_r = [
                [w / 2.0 - 0.03, 0.0, rail_h],
                [w / 2.0 - 0.03, total_run, total_height + rail_h],
            ]
            self.create_curve_sweep(f"{name}_Rail_L", path_points_3d=rail_l, radius=0.02, parent_name=name)
            self.create_curve_sweep(f"{name}_Rail_R", path_points_3d=rail_r, radius=0.02, parent_name=name)

        return {"success": True, "staircase": obj.name, "step_count": steps, "riser_height": round(dh, 4)}

    def create_building_shell(
        self,
        name: str = "Building",
        width: float = 12.0,
        depth: float = 12.0,
        floors: int = 6,
        floor_height: float = 3.2,
        window_cols_x: int = 4,
        window_cols_y: int = 4,
        window_width: float = 1.5,
        window_height: float = 1.8,
        facade_color: Optional[List[float]] = None,
        glass_color: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Construye un edificio o rascacielos completo con losas de entrepiso, fachada de vidrio y parapeto superior."""
        total_h = floors * floor_height

        # Núcleo / Fachada principal
        core = self.create_parametric_part(
            name=name,
            shape="ROUNDED_BOX",
            dimensions=[width, depth, total_h],
            location=[0, 0, 0],
            origin="BOTTOM",
            bevel_width=0.05,
            color=facade_color or [0.88, 0.88, 0.88, 1.0]
        )

        # Cornisa de techo y parapeto
        parapet = self.create_parametric_part(
            name=f"{name}_RoofParapet",
            shape="BOX",
            dimensions=[width + 0.2, depth + 0.2, 0.8],
            location=[0, 0, total_h],
            origin="BOTTOM",
            parent_name=name,
            color=[0.25, 0.25, 0.25, 1.0]
        )

        # Losas perimetrales que TOcan la fachada sin tragar la columna: 4 placas
        # por nivel cuyas caras internas quedan coplanares con el núcleo
        # (junta informativa, no fallo). Una losa sólida envolvería la columna
        # y el audit la marcaría como interpenetración real.
        _slab_t = 0.15
        for fl in range(1, floors):
            zc = fl * floor_height
            for side, dims, loc in [
                (f"{name}_Slab_Fl{fl}_F", [width + 0.15, 0.075, _slab_t], [0, depth / 2.0 + 0.0375, zc]),
                (f"{name}_Slab_Fl{fl}_B", [width + 0.15, 0.075, _slab_t], [0, -depth / 2.0 - 0.0375, zc]),
                (f"{name}_Slab_Fl{fl}_L", [0.075, depth, _slab_t], [-width / 2.0 - 0.0375, 0, zc]),
                (f"{name}_Slab_Fl{fl}_R", [0.075, depth, _slab_t], [width / 2.0 + 0.0375, 0, zc]),
            ]:
                self.create_parametric_part(
                    name=side, shape="BOX", dimensions=dims, location=loc,
                    origin="CENTER", parent_name=name, bevel_width=0.0,
                    color=[0.3, 0.3, 0.3, 1.0]
                )

        # Grilla de ventanas en las fachadas frontal (-Y) y posterior (+Y)
        mat_glass = f"{name}_GlassMat"
        self.create_material(mat_glass, color=glass_color or [0.2, 0.5, 0.7, 1.0], roughness=0.05, alpha=0.35)

        dx = width / (window_cols_x + 1)
        for fl in range(floors):
            w_z = fl * floor_height + floor_height / 2.0
            for col in range(1, window_cols_x + 1):
                w_x = -width / 2.0 + col * dx
                # Moldura superficial: cara interna coplanar con la fachada
                # (toca sin empotrar; empotrada marcaría overlap real).
                for suffix, wy in (("F", -depth / 2.0 - 0.025), ("B", depth / 2.0 + 0.025)):
                    self.create_parametric_part(
                        name=f"{name}_Win_{suffix}_Fl{fl}_C{col}",
                        shape="BOX",
                        dimensions=[window_width, 0.05, window_height],
                        location=[w_x, wy, w_z],
                        origin="CENTER",
                        parent_name=name,
                        material_name=mat_glass
                    )

        return {"success": True, "building": name, "floors": floors, "total_height": total_h, "world_aabb": self._get_aabb(bpy.data.objects.get(name))}

    def array_grid_on_surface(
        self,
        module_name: str,
        target_name: str,
        face: str = "FRONT",
        rows: int = 3,
        cols: int = 4,
        margin_u: float = 0.4,
        margin_v: float = 0.4,
        penetration: float = 0.005,
        instance_data: bool = True,
    ) -> Dict[str, Any]:
        """Distribuye un objeto módulo (balcón, ventana, panel) en una grilla regular acoplada a una cara del objetivo."""
        mod = bpy.data.objects.get(module_name)
        target = bpy.data.objects.get(target_name)
        if not mod or not target:
            raise ValueError(f"Module '{module_name}' or Target '{target_name}' not found")

        t_aabb = self._get_aabb(target)
        tx_min, ty_min, tz_min = t_aabb[0]
        tx_max, ty_max, tz_max = t_aabb[1]

        f_upper = face.upper()
        if f_upper == "FRONT":  # -Y face
            u_min, u_max = tx_min + margin_u, tx_max - margin_u
            v_min, v_max = tz_min + margin_v, tz_max - margin_v
            fixed_y = ty_min + penetration
        elif f_upper == "BACK":  # +Y face
            u_min, u_max = tx_min + margin_u, tx_max - margin_u
            v_min, v_max = tz_min + margin_v, tz_max - margin_v
            fixed_y = ty_max - penetration
        elif f_upper == "LEFT":  # -X face
            u_min, u_max = ty_min + margin_u, ty_max - margin_u
            v_min, v_max = tz_min + margin_v, tz_max - margin_v
            fixed_x = tx_min + penetration
        elif f_upper == "RIGHT":  # +X face
            u_min, u_max = ty_min + margin_u, ty_max - margin_u
            v_min, v_max = tz_min + margin_v, tz_max - margin_v
            fixed_x = tx_max - penetration
        else:  # TOP
            u_min, u_max = tx_min + margin_u, tx_max - margin_u
            v_min, v_max = ty_min + margin_v, ty_max - margin_v
            fixed_z = tz_max - penetration

        du = (u_max - u_min) / max(1, cols - 1) if cols > 1 else 0.0
        dv = (v_max - v_min) / max(1, rows - 1) if rows > 1 else 0.0

        spawned = []
        for r in range(rows):
            v_pos = v_min + r * dv
            for c in range(cols):
                u_pos = u_min + c * du
                dup_mesh = mod.data if instance_data else mod.data.copy()
                dup_obj = bpy.data.objects.new(f"{module_name}_G_{r}_{c}", dup_mesh)
                bpy.context.collection.objects.link(dup_obj)

                if f_upper in ("FRONT", "BACK"):
                    dup_obj.location = Vector((u_pos, fixed_y, v_pos))
                elif f_upper in ("LEFT", "RIGHT"):
                    dup_obj.location = Vector((fixed_x, u_pos, v_pos))
                else:
                    dup_obj.location = Vector((u_pos, v_pos, fixed_z))

                dup_obj.parent = target
                dup_obj.matrix_parent_inverse = target.matrix_world.inverted()
                spawned.append(dup_obj.name)

        return {"success": True, "module": module_name, "grid_count": len(spawned), "spawned": spawned}

    # ==========================================================================
    # 6. AUDIT, TOPOLOGY REPAIR & SELF-CORRECTION
    # ==========================================================================
    def audit_3d_model(
        self,
        object_names: Optional[List[str]] = None,
        blueprint_name: Optional[str] = None,
        contact_tolerance: float = 0.018,
        suspended: Optional[List[str]] = None,
        ground_tolerance: float = 0.005,
        scale_tolerance: float = 1e-3,
        symmetry_axis: Optional[str] = None,
        symmetry_plane: float = 0.0,
        symmetry_tolerance: float = 1e-3,
        topology_policy: str = "report",
        check_self_intersections: bool = False,
    ) -> Dict[str, Any]:
        """Audit evaluated geometry. AABB is broad-phase; `passed` is computed last."""
        bpy.context.view_layer.update()
        candidates = (
            [bpy.data.objects.get(name) for name in object_names]
            if object_names
            else list(bpy.context.scene.objects)
        )

        mesh_objects: List[bpy.types.Object] = []
        snapshots: Dict[str, GeometrySnapshot] = {}
        for obj in candidates:
            if not obj or obj.type != "MESH":
                continue
            try:
                snapshots[obj.name] = GeometryService.snapshot(obj)
            except (TypeError, ValueError):
                continue
            mesh_objects.append(obj)

        units = {
            "system": bpy.context.scene.unit_settings.system,
            "scale_length": float(bpy.context.scene.unit_settings.scale_length or 1.0),
            "length_unit": bpy.context.scene.unit_settings.length_unit,
        }
        suspended_set = {str(name) for name in (suspended or [])}

        if not mesh_objects:
            message = "NO_MESH_OBJECTS: no evaluated mesh objects to audit."
            return {
                "passed": False,
                "quality_score": 0,
                "requirements": {"objects_present": {"passed": False, "actual": 0}},
                "dimensions": {
                    "units": units,
                    "assembly_world_aabb": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                    "assembly_dimensions": [0.0, 0.0, 0.0],
                    "objects": {},
                },
                "topology": {},
                "contacts": {
                    "tolerance": float(contact_tolerance),
                    "objects": [],
                    "pairs": [],
                },
                "collisions": [],
                "symmetry": None,
                "warnings": [message],
                "failures": [{
                    "rule": "objects_present",
                    "object": "assembly",
                    "expected": ">=1 evaluated mesh",
                    "actual": 0,
                    "tolerance": 0,
                    "method": "evaluated_mesh",
                    "severity": "critical",
                }],
                "critical_issues": [message],
                "joints": [],
                "llm_fix_commands": [],
                "suspended": [],
                "blueprint": None,
                "assembly_world_aabb": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                "object_count_audited": 0,
            }

        structural = [obj for obj in mesh_objects if obj.name not in suspended_set]
        warnings: List[str] = []
        failures: List[Dict[str, Any]] = []
        joints: List[str] = []
        llm_fix_commands: List[str] = []
        requirements: Dict[str, Any] = {}

        # 1. Collect dimensions from evaluated geometry.
        assembly_min = [float("inf")] * 3
        assembly_max = [float("-inf")] * 3
        objects_dimensions: Dict[str, Any] = {}
        for obj in mesh_objects:
            snapshot = snapshots[obj.name]
            dimensions = [
                snapshot.world_aabb[1][axis] - snapshot.world_aabb[0][axis]
                for axis in range(3)
            ]
            objects_dimensions[obj.name] = {
                "world_aabb": snapshot.world_aabb,
                "local_aabb": snapshot.local_aabb,
                "dimensions": [round(value, 6) for value in dimensions],
                "unit_scale": snapshot.unit_scale,
                "face_count": snapshot.face_count,
            }
            if obj.name in suspended_set:
                continue
            for axis in range(3):
                assembly_min[axis] = min(assembly_min[axis], snapshot.world_aabb[0][axis])
                assembly_max[axis] = max(assembly_max[axis], snapshot.world_aabb[1][axis])

        if assembly_min[0] == float("inf"):
            assembly_aabb = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
            assembly_dimensions = [0.0, 0.0, 0.0]
        else:
            assembly_aabb = [
                [round(value, 6) for value in assembly_min],
                [round(value, 6) for value in assembly_max],
            ]
            assembly_dimensions = [
                round(assembly_max[axis] - assembly_min[axis], 6)
                for axis in range(3)
            ]

        dimensions_report = {
            "units": units,
            "assembly_world_aabb": assembly_aabb,
            "assembly_dimensions": assembly_dimensions,
            "objects": objects_dimensions,
        }

        # 2. Ground contact.
        structural_snapshots = [snapshots[obj.name] for obj in structural]
        ground = GeometryService.ground_contact(structural_snapshots, ground_tolerance)
        requirements["ground_contact"] = {
            "passed": ground["passed"],
            "tolerance": float(ground_tolerance),
            "actual": ground["min_z"],
            "method": ground["method"],
        }
        if structural_snapshots and not ground["passed"]:
            failures.append({
                "rule": "ground_contact",
                "object": "assembly",
                "expected": 0.0,
                "actual": ground["min_z"],
                "tolerance": float(ground_tolerance),
                "method": ground["method"],
                "severity": "critical",
            })
            if "ground_model()" not in llm_fix_commands:
                llm_fix_commands.append("ground_model()")

        # 3. Normalized scale.
        bad_scale: List[Dict[str, Any]] = []
        for obj in mesh_objects:
            if any(abs(abs(value) - 1.0) > scale_tolerance for value in obj.scale):
                entry = {
                    "object": obj.name,
                    "scale": [round(float(value), 6) for value in obj.scale],
                }
                bad_scale.append(entry)
                warnings.append(
                    f"UNAPPLIED_SCALE on '{obj.name}': scale is {entry['scale']}. "
                    "Must have absolute scale (1,1,1); negative values are mirrors."
                )
                command = f"repair_mesh_geometry(object_names=['{obj.name}'])"
                if command not in llm_fix_commands:
                    llm_fix_commands.append(command)
                failures.append({
                    "rule": "normalized_scale",
                    "object": obj.name,
                    "expected": [1.0, 1.0, 1.0],
                    "actual": entry["scale"],
                    "tolerance": float(scale_tolerance),
                    "method": "object_scale",
                    "severity": "critical",
                })
        requirements["normalized_scale"] = {
            "passed": not bad_scale,
            "tolerance": float(scale_tolerance),
            "objects": bad_scale,
            "method": "object_scale",
        }

        # 4. Contact graph and collisions. AABB is broad-phase only; a
        # collision claim comes from BVH triangle intersection.
        contact_graph = GeometryService.contact_graph(
            mesh_objects, tolerance=contact_tolerance
        )
        collisions: List[Dict[str, Any]] = []
        floating: List[Dict[str, Any]] = []

        for pair in contact_graph["pairs"]:
            if pair["surface_intersection"]:
                aabb_a = snapshots[pair["a"]].world_aabb
                aabb_b = snapshots[pair["b"]].world_aabb
                if self._is_face_contact(aabb_a, aabb_b):
                    joints.append(
                        f"CONTACT_JOINT between '{pair['a']}' and '{pair['b']}': "
                        f"surfaces touch ({pair['overlap_face_pairs']} face pairs, "
                        f"estimated area {pair['estimated_contact_area']} m2, "
                        f"method={pair['method']})."
                    )
                else:
                    collisions.append(pair)
                    failures.append({
                        "rule": "no_surface_intersection",
                        "object": f"{pair['a']} <-> {pair['b']}",
                        "expected": "no surface intersection",
                        "actual": f"{pair['overlap_face_pairs']} overlapping face pairs",
                        "tolerance": float(contact_tolerance),
                        "method": pair["method"],
                        "confidence": pair["confidence"],
                        "severity": "critical",
                    })
                    command = f"auto_fix_model(object_names=['{pair['a']}', '{pair['b']}'])"
                    if command not in llm_fix_commands:
                        llm_fix_commands.append(command)
                continue

            object_a = bpy.data.objects.get(pair["a"])
            object_b = bpy.data.objects.get(pair["b"])
            if not object_a or not object_b:
                continue
            if not (object_a.parent == object_b or object_b.parent == object_a):
                continue
            if object_a.name in suspended_set or object_b.name in suspended_set:
                continue
            if pair["min_distance"] <= contact_tolerance:
                continue

            child = object_a.name if object_a.parent == object_b else object_b.name
            parent = object_b.name if child == object_a.name else object_a.name
            floating.append({
                "child": child,
                "parent": parent,
                "gap": pair["min_distance"],
                "method": pair["method"],
                "approximate": pair["approximate"],
            })
            failures.append({
                "rule": "parent_child_contact",
                "object": child,
                "expected": f"gap <= {contact_tolerance}",
                "actual": pair["min_distance"],
                "tolerance": float(contact_tolerance),
                "method": pair["method"],
                "severity": "critical",
            })
            command = f"attach_and_align(part_name='{child}', target_name='{parent}', relation='ON_TOP')"
            if command not in llm_fix_commands:
                llm_fix_commands.append(command)

        requirements["no_surface_intersection"] = {
            "passed": not collisions,
            "tolerance": float(contact_tolerance),
            "collision_pairs": len(collisions),
            "method": "bvh_overlap",
        }
        requirements["parent_child_contact"] = {
            "passed": not floating,
            "tolerance": float(contact_tolerance),
            "floating": floating,
            "method": "contact_graph",
        }

        # 5. Topology metrics. Report by default; strict mode makes defects
        # blocking.
        if topology_policy not in ("report", "strict"):
            warnings.append(
                f"UNKNOWN_TOPOLOGY_POLICY '{topology_policy}': using 'report'."
            )
            topology_policy = "report"

        topology: Dict[str, Any] = {}
        topology_issues: List[Dict[str, Any]] = []
        for obj in mesh_objects:
            try:
                metrics = GeometryService.topology_metrics(
                    obj, check_self_intersections=check_self_intersections
                )
            except Exception as exc:
                warnings.append(f"TOPOLOGY_ERROR on '{obj.name}': {exc}")
                continue
            topology[obj.name] = metrics

            checks = (
                ("non_manifold_edges", "TOPOLOGY_NON_MANIFOLD"),
                ("loose_vertices", "TOPOLOGY_LOOSE_VERTICES"),
                ("zero_area_faces", "TOPOLOGY_ZERO_AREA"),
                ("self_intersections", "TOPOLOGY_SELF_INTERSECTIONS"),
            )
            for key, label in checks:
                count = metrics.get(key)
                if count:
                    topology_issues.append({
                        "object": obj.name,
                        "rule": key,
                        "count": count,
                    })
                    warnings.append(f"{label} on '{obj.name}': {count}.")
            if metrics.get("inverted_normals"):
                warnings.append(
                    f"TOPOLOGY_INVERTED_NORMALS on '{obj.name}': "
                    f"{metrics['inverted_normals']} (recalc heuristic)."
                )

        requirements["topology"] = {
            "passed": True if topology_policy == "report" else not topology_issues,
            "policy": topology_policy,
            "objects_with_issues": sorted({issue["object"] for issue in topology_issues}),
        }
        if topology_policy == "strict":
            for issue in topology_issues:
                failures.append({
                    "rule": issue["rule"],
                    "object": issue["object"],
                    "expected": 0,
                    "actual": issue["count"],
                    "tolerance": 0,
                    "method": "bmesh_evaluated",
                    "severity": "critical",
                })

        # 6. Symmetry (optional).
        symmetry = None
        if symmetry_axis:
            try:
                symmetry = GeometryService.symmetry_error(
                    structural,
                    axis=symmetry_axis,
                    plane=symmetry_plane,
                    tolerance=symmetry_tolerance,
                )
                requirements["symmetry"] = {
                    "passed": symmetry["passed"],
                    "tolerance": float(symmetry_tolerance),
                    "actual_max_error": symmetry["max_error"],
                    "method": symmetry["method"],
                    "confidence": symmetry["confidence"],
                }
                if not symmetry["passed"]:
                    failures.append({
                        "rule": "symmetry",
                        "object": "assembly",
                        "expected": f"max error <= {symmetry_tolerance}",
                        "actual": symmetry["max_error"],
                        "tolerance": float(symmetry_tolerance),
                        "method": symmetry["method"],
                        "severity": "critical",
                    })
            except Exception as exc:
                warnings.append(f"SYMMETRY_ERROR: {exc}")

        # 7. Blueprint dimensions. This runs before `passed` is computed.
        blueprint_report = None
        if blueprint_name:
            blueprint = MODELING_BLUEPRINTS.get(str(blueprint_name).lower().strip())
            if blueprint is None:
                warnings.append(
                    f"UNKNOWN_BLUEPRINT '{blueprint_name}': no proportion reference applied."
                )
            else:
                expected = [float(value) for value in blueprint.get("dimensions", [])]
                actual = assembly_dimensions
                relative_tolerance = float(blueprint.get("tolerance", 0.30))
                tolerance = Tolerance(
                    absolute=0.0005, relative=relative_tolerance
                )
                blueprint_report = {
                    "name": str(blueprint_name),
                    "expected_dimensions": expected,
                    "actual_dimensions": actual,
                    "tolerance": relative_tolerance,
                    "tolerance_model": {
                        "absolute": tolerance.absolute,
                        "relative": tolerance.relative,
                    },
                    "rescale_factors": None,
                    "rescale_suggestion": None,
                    "passed": True,
                }
                if len(expected) != 3:
                    warnings.append(
                        f"BLUEPRINT_NO_DIMENSIONS '{blueprint_name}': cannot compare proportions."
                    )
                    expected = []
                    blueprint_report["passed"] = False
                dimensions_available = len(expected) == 3

                mismatches = []
                for axis, label in ((0, "X"), (1, "Y"), (2, "Z")):
                    if not expected or expected[axis] <= 1e-6:
                        continue
                    allowed = tolerance.allowed(expected[axis])
                    if abs(actual[axis] - expected[axis]) > allowed:
                        mismatches.append({
                            "axis": label,
                            "expected": expected[axis],
                            "actual": actual[axis],
                            "tolerance": round(allowed, 6),
                        })
                        failures.append({
                            "rule": "blueprint_dimensions",
                            "object": "assembly",
                            "expected": expected[axis],
                            "actual": actual[axis],
                            "tolerance": round(allowed, 6),
                            "method": "evaluated_world_aabb",
                            "axis": label,
                            "severity": "critical",
                        })
                        if len(mesh_objects) == 1:
                            command = (
                                f"transform_object(name='{mesh_objects[0].name}', "
                                f"dimensions=[{expected[0]}, {expected[1]}, {expected[2]}])"
                            )
                            if command not in llm_fix_commands:
                                llm_fix_commands.append(command)

                if not dimensions_available:
                    failures.append({
                        "rule": "blueprint_dimensions",
                        "object": "assembly",
                        "expected": "3 blueprint dimensions",
                        "actual": len(expected),
                        "tolerance": 0,
                        "method": "blueprint",
                        "severity": "critical",
                    })
                    requirements["blueprint_dimensions"] = {
                        "passed": False,
                        "tolerance": relative_tolerance,
                        "mismatches": [],
                        "method": "blueprint",
                    }
                elif mismatches:
                    blueprint_report["passed"] = False
                    factors = [
                        round(expected[index] / actual[index], 4)
                        if actual[index] > 1e-6
                        else None
                        for index in range(3)
                    ]
                    blueprint_report["rescale_factors"] = factors
                    blueprint_report["rescale_suggestion"] = (
                        "Parent the roots to an empty and scale it uniformly, or per root: "
                        "transform_object(scale=[fx,fy,fz]) AND scale its location by the same "
                        "factors, then ground_model() and re-audit. Verify visually."
                    )
                    requirements["blueprint_dimensions"] = {
                        "passed": False,
                        "tolerance": relative_tolerance,
                        "mismatches": mismatches,
                        "method": "evaluated_world_aabb",
                    }
                else:
                    requirements["blueprint_dimensions"] = {
                        "passed": True,
                        "tolerance": relative_tolerance,
                        "mismatches": [],
                        "method": "evaluated_world_aabb",
                    }

                bounds = blueprint.get("bounds", {})
                aspect = bounds.get("aspect_xy")
                if aspect and actual[1] > 1e-6:
                    ratio = actual[0] / actual[1]
                    if not (aspect[0] <= ratio <= aspect[1]):
                        warnings.append(
                            f"BLUEPRINT_PROPORTION_OFF: X/Y aspect {ratio:.2f} outside "
                            f"blueprint '{blueprint_name}' range {aspect}."
                        )

        # 8. Score and final verdict. `passed` is last.
        critical_count = sum(
            1 for failure in failures if failure.get("severity") == "critical"
        )
        quality_score = max(0, 100 - critical_count * 25 - len(warnings) * 5)
        passed = (
            critical_count == 0
            and all(requirement.get("passed", False) for requirement in requirements.values())
        )

        critical_issues = [
            f"{failure['rule'].upper()} on '{failure['object']}': expected "
            f"{failure['expected']!r}, got {failure['actual']!r} "
            f"(tolerance {failure['tolerance']!r}, method {failure['method']})."
            for failure in failures
            if failure.get("severity") == "critical"
        ]

        return {
            "passed": passed,
            "quality_score": quality_score,
            "requirements": requirements,
            "dimensions": dimensions_report,
            "topology": topology,
            "contacts": contact_graph,
            "collisions": collisions,
            "symmetry": symmetry,
            "warnings": warnings,
            "failures": failures,
            # Legacy views consumed by existing prompts.
            "critical_issues": critical_issues,
            "joints": joints,
            "llm_fix_commands": llm_fix_commands,
            "suspended": sorted(
                name for name in suspended_set if bpy.data.objects.get(name)
            ),
            "blueprint": blueprint_report,
            "assembly_world_aabb": assembly_aabb,
            "object_count_audited": len(mesh_objects),
        }

    def repair_mesh_geometry(
        self,
        object_names: Optional[List[str]] = None,
        merge_distance: float = 0.0005,
        recalc_normals: bool = True,
        apply_scale: bool = True,
        shade_smooth: bool = True,
    ) -> Dict[str, Any]:
        """Sana la topología, elimina vértices dobles y recalcula normales preservando hijos."""
        objs = [bpy.data.objects.get(n) for n in object_names] if object_names else list(bpy.context.scene.objects)
        repaired = []

        for obj in objs:
            if not obj or obj.type != "MESH" or not obj.data:
                continue

            mesh = obj.data
            if apply_scale:
                sx, sy, sz = float(obj.scale.x), float(obj.scale.y), float(obj.scale.z)
                if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
                    children_world = [(c, c.matrix_world.copy()) for c in obj.children]
                    scale_mat = Matrix.Diagonal((sx, sy, sz, 1.0))
                    mesh.transform(scale_mat)
                    obj.scale = Vector((1.0, 1.0, 1.0))
                    bpy.context.view_layer.update()
                    for child_obj, child_mat in children_world:
                        child_obj.matrix_parent_inverse = obj.matrix_world.inverted()
                        child_obj.matrix_world = child_mat

            bm = bmesh.new()
            bm.from_mesh(mesh)
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=merge_distance)
            if recalc_normals:
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            if shade_smooth:
                for f in bm.faces:
                    f.smooth = True
            bm.to_mesh(mesh)
            bm.free()

            self._auto_box_uv_unwrap(mesh)
            repaired.append(obj.name)

        return {"success": True, "repaired_objects": repaired}

    def ground_model(
        self,
        object_names: Optional[List[str]] = None,
        center_xy: bool = True,
    ) -> Dict[str, Any]:
        """Desplaza todo el ensamble rígidamente para que su base descanse en Z=0.0."""
        objs = [bpy.data.objects.get(n) for n in object_names] if object_names else list(bpy.context.scene.objects)
        mesh_objs = [o for o in objs if o and o.type == "MESH"]
        if not mesh_objs:
            return {"success": False, "message": "No mesh objects found to ground"}

        bpy.context.view_layer.update()
        global_min = [float("inf")] * 3
        global_max = [float("-inf")] * 3

        for o in mesh_objs:
            aabb = self._get_aabb(o)
            for i in range(3):
                global_min[i] = min(global_min[i], aabb[0][i])
                global_max[i] = max(global_max[i], aabb[1][i])

        dz = -global_min[2]
        dx = -(global_min[0] + global_max[0]) / 2.0 if center_xy else 0.0
        dy = -(global_min[1] + global_max[1]) / 2.0 if center_xy else 0.0
        trans = Vector((dx, dy, dz))

        # Trasladar únicamente objetos raíz (sin padre dentro de la selección)
        root_objs = [o for o in mesh_objs if o.parent not in mesh_objs]
        for r in root_objs:
            r.location += trans

        bpy.context.view_layer.update()
        return {"success": True, "ground_translation": [round(c, 5) for c in trans]}

    def auto_fix_model(
        self,
        object_names: Optional[List[str]] = None,
        snap_floating_threshold: float = 0.35,
        center_xy: bool = True,
        snap_floating: bool = True,
        suspended: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Corrige topología, cierra holguras con BVHTree y asienta el modelo en Z=0.0.

        Lo suspendido (lámparas, cables) no se acerca a nada con snap, pero sí
        viaja con el ground rígido (conserva su altura relativa) y se informa
        al audit final para no remarcarlo.
        """
        suspended_set = {str(n) for n in (suspended or [])}
        self.repair_mesh_geometry(object_names=object_names, apply_scale=True)
        objs = [bpy.data.objects.get(n) for n in object_names] if object_names else list(bpy.context.scene.objects)
        mesh_objs = [o for o in objs if o and o.type == "MESH"]

        if snap_floating and len(mesh_objs) > 1:
            for i in range(len(mesh_objs)):
                for j in range(len(mesh_objs)):
                    if i == j:
                        continue
                    oa, ob = mesh_objs[i], mesh_objs[j]
                    if oa.name in suspended_set or ob.name in suspended_set:
                        continue
                    gap, delta, _ = self._compute_surface_gap_and_overlap(oa, ob)
                    if 0.005 < gap < snap_floating_threshold:
                        oa.location += Vector(delta)
                        bpy.context.view_layer.update()
                        break

        self.ground_model(object_names=object_names, center_xy=center_xy)
        return self.audit_3d_model(object_names=object_names, suspended=suspended)
        return self.audit_3d_model(object_names=object_names, suspended=suspended)

    # ==========================================================================
    # 7. MULTI-VIEW QUAD VISUAL CRITIC & STUDIO LIGHTING
    # ==========================================================================
    def render_multiview_inspection(
        self,
        object_names: Optional[List[str]] = None,
        resolution: int = 512,
        show_wireframe: bool = False,
        blueprint_name: Optional[str] = None,
        return_base64: bool = True,
        suspended: Optional[List[str]] = None,
        mode: str = "quad",
        include_overlays: bool = False,
    ) -> Dict[str, Any]:
        """Render deterministic inspection views with documented cameras and metadata."""
        bpy.context.view_layer.update()
        resolution = max(64, min(int(resolution), 2048))
        audit = self.audit_3d_model(
            object_names=object_names,
            blueprint_name=blueprint_name,
            suspended=suspended,
        )
        aabb = audit.get("assembly_world_aabb", [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        center = Vector((
            (aabb[0][0] + aabb[1][0]) / 2.0,
            (aabb[0][1] + aabb[1][1]) / 2.0,
            (aabb[0][2] + aabb[1][2]) / 2.0,
        ))
        extents = [
            max(aabb[1][axis] - aabb[0][axis], 0.001)
            for axis in range(3)
        ]
        size = max(max(extents), 0.5)
        distance = size * 3.0 + 1.0
        perspective_distance = max(size * 2.2, 1.0)

        views = {
            "front": {
                "name": "FRONT",
                "label": "Top-Left: FRONT (-Y)",
                "camera_type": "ORTHO",
                "position": center + Vector((0.0, -distance, 0.0)),
                "rotation": Euler((math.radians(90), 0.0, 0.0), "XYZ"),
                "ortho_scale": max(extents[0], extents[2]) * 1.2,
                "lens": None,
            },
            "side": {
                "name": "RIGHT",
                "label": "Top-Right: RIGHT (+X)",
                "camera_type": "ORTHO",
                "position": center + Vector((distance, 0.0, 0.0)),
                "rotation": Euler((math.radians(90), 0.0, math.radians(90)), "XYZ"),
                "ortho_scale": max(extents[1], extents[2]) * 1.2,
                "lens": None,
            },
            "top": {
                "name": "TOP",
                "label": "Bottom-Left: TOP (+Z)",
                "camera_type": "ORTHO",
                "position": center + Vector((0.0, 0.0, distance)),
                "rotation": Euler((0.0, 0.0, 0.0), "XYZ"),
                "ortho_scale": max(extents[0], extents[1]) * 1.2,
                "lens": None,
            },
            "iso": {
                "name": "ISO",
                "label": "Bottom-Right: ISOMETRIC (3/4)",
                "camera_type": "PERSP",
                "position": center + Vector((
                    perspective_distance * 0.707,
                    -perspective_distance * 0.707,
                    perspective_distance * 0.6,
                )),
                "rotation": Euler((math.radians(60), 0.0, math.radians(45)), "XYZ"),
                "ortho_scale": None,
                "lens": 50.0,
            },
        }

        allowed_modes = {
            "quad", "front", "side", "top", "iso",
            "silhouette", "wireframe", "normals", "uv_checker",
        }
        if mode not in allowed_modes:
            raise ValueError(f"Invalid mode '{mode}'. Allowed: {sorted(allowed_modes)}")

        if mode == "quad":
            selected_views = [views["front"], views["side"], views["top"], views["iso"]]
        elif mode in ("front", "side", "top", "iso"):
            selected_views = [views[mode]]
        else:
            selected_views = [views["iso"]]

        shading_kind = {
            "quad": "gray",
            "front": "gray",
            "side": "gray",
            "top": "gray",
            "iso": "gray",
            "silhouette": "white",
            "wireframe": "white",
            "normals": "normals",
            "uv_checker": "checker",
        }[mode]

        settings_key = {
            "mode": mode,
            "resolution": resolution,
            "views": [
                {
                    "name": view["name"],
                    "camera_type": view["camera_type"],
                    "position": list(view["position"]),
                    "rotation": list(view["rotation"]),
                    "ortho_scale": view["ortho_scale"],
                    "lens": view["lens"],
                }
                for view in selected_views
            ],
            "aabb": aabb,
            "overlays": include_overlays,
            "show_wireframe": show_wireframe,
            "engine": "BLENDER_EEVEE_NEXT",
        }
        render_id = hashlib.sha256(
            json.dumps(settings_key, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        output_root = os.path.abspath(os.path.expanduser(
            os.environ.get("BLENDER_MCP_OUTPUT_DIR") or default_output_dir()
        ))
        output_dir = os.path.join(output_root, "inspection", render_id)
        os.makedirs(output_dir, exist_ok=True)

        scene = bpy.context.scene
        render = scene.render
        view_layer = scene.view_layers[0]
        old_state = {
            "camera": scene.camera,
            "engine": render.engine,
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "resolution_percentage": render.resolution_percentage,
            "film_transparent": render.film_transparent,
            "filepath": render.filepath,
            "file_format": render.image_settings.file_format,
            "color_mode": render.image_settings.color_mode,
            "compression": render.image_settings.compression,
            "material_override": view_layer.material_override,
            "world": scene.world,
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "exposure": scene.view_settings.exposure,
            "gamma": scene.view_settings.gamma,
            "eevee_samples": getattr(scene.eevee, "taa_render_samples", None),
        }

        cam_data = bpy.data.cameras.new("InspectionCam")
        cam_obj = bpy.data.objects.new("InspectionCam", cam_data)
        scene.collection.objects.link(cam_obj)
        scene.camera = cam_obj
        cam_data.clip_start = 0.001
        cam_data.clip_end = max(100.0, distance * 8.0)

        created_lights: List[bpy.types.Object] = []
        created_materials: List[bpy.types.Material] = []
        hidden_lights: List[bpy.types.Object] = []
        wireframe_copies: List[bpy.types.Object] = []
        hidden_objects: List[bpy.types.Object] = []
        overlay_obj: Optional[bpy.types.Object] = None
        inspection_world: Optional[bpy.types.World] = None

        try:
            render.engine = "BLENDER_EEVEE_NEXT"
            if old_state["eevee_samples"] is not None:
                scene.eevee.taa_render_samples = 16
            render.resolution_x = resolution
            render.resolution_y = resolution
            render.resolution_percentage = 100
            render.film_transparent = False
            render.image_settings.file_format = "PNG"
            render.image_settings.color_mode = "RGB"
            render.image_settings.compression = 15
            with suppress(Exception):
                scene.view_settings.view_transform = "Standard"
                scene.view_settings.look = "None"
                scene.view_settings.exposure = 0.0
                scene.view_settings.gamma = 1.0

            for obj in list(scene.objects):
                if obj.type == "LIGHT" and not obj.hide_render:
                    obj.hide_render = True
                    hidden_lights.append(obj)

            inspection_world = bpy.data.worlds.new("InspectionWorld")
            inspection_world.use_nodes = True
            background = inspection_world.node_tree.nodes["Background"]
            background.inputs[0].default_value = (0.02, 0.02, 0.02, 1.0)
            background.inputs[1].default_value = 0.35
            scene.world = inspection_world

            def make_material(kind: str) -> bpy.types.Material:
                material = bpy.data.materials.new(f"Inspection_{kind}")
                material.use_nodes = True
                nodes = material.node_tree.nodes
                links = material.node_tree.links
                nodes.clear()
                output = nodes.new("ShaderNodeOutputMaterial")
                if kind == "gray":
                    shader = nodes.new("ShaderNodeBsdfPrincipled")
                    shader.inputs["Base Color"].default_value = (0.55, 0.57, 0.60, 1.0)
                    shader.inputs["Roughness"].default_value = 0.55
                    links.new(shader.outputs[0], output.inputs[0])
                elif kind == "white":
                    shader = nodes.new("ShaderNodeEmission")
                    shader.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
                    links.new(shader.outputs[0], output.inputs[0])
                elif kind == "normals":
                    geometry = nodes.new("ShaderNodeNewGeometry")
                    vector_math = nodes.new("ShaderNodeVectorMath")
                    vector_math.operation = "MULTIPLY_ADD"
                    vector_math.inputs[1].default_value = (0.5, 0.5, 0.5)
                    vector_math.inputs[2].default_value = (0.5, 0.5, 0.5)
                    shader = nodes.new("ShaderNodeEmission")
                    links.new(geometry.outputs["Normal"], vector_math.inputs[0])
                    links.new(vector_math.outputs[0], shader.inputs["Color"])
                    links.new(shader.outputs[0], output.inputs[0])
                elif kind == "checker":
                    coordinates = nodes.new("ShaderNodeTexCoord")
                    checker = nodes.new("ShaderNodeTexChecker")
                    checker.inputs["Scale"].default_value = 8.0
                    checker.inputs["Color1"].default_value = (0.85, 0.20, 0.20, 1.0)
                    checker.inputs["Color2"].default_value = (0.10, 0.20, 0.85, 1.0)
                    shader = nodes.new("ShaderNodeEmission")
                    links.new(coordinates.outputs["UV"], checker.inputs["Vector"])
                    links.new(checker.outputs[0], shader.inputs["Color"])
                    links.new(shader.outputs[0], output.inputs[0])
                else:
                    raise ValueError(f"Unknown inspection material '{kind}'")
                created_materials.append(material)
                return material

            materials = {
                "gray": make_material("gray"),
                "white": make_material("white"),
                "normals": make_material("normals"),
                "checker": make_material("checker"),
            }

            saved_materials: List[Tuple[bpy.types.Object, List[Optional[bpy.types.Material]]]] = []
            current_material: Optional[bpy.types.Material] = None

            def restore_materials() -> None:
                nonlocal current_material
                for obj, slots in reversed(saved_materials):
                    try:
                        obj.data.materials.clear()
                        for slot in slots:
                            obj.data.materials.append(slot)
                    except ReferenceError:
                        continue
                saved_materials.clear()
                current_material = None

            def apply_material(material: bpy.types.Material) -> None:
                nonlocal current_material
                if current_material is material:
                    return
                restore_materials()
                current_material = material
                for obj in list(scene.objects):
                    if obj.type != "MESH":
                        continue
                    slots = [slot.material for slot in obj.material_slots]
                    saved_materials.append((obj, slots))
                    if obj.data.materials:
                        for index in range(len(obj.data.materials)):
                            obj.data.materials[index] = material
                    else:
                        obj.data.materials.append(material)

            key_light: Optional[bpy.types.Object] = None

            def ensure_key_light() -> bpy.types.Object:
                nonlocal key_light
                if key_light is None:
                    light_data = bpy.data.lights.new("InspectionSun", "SUN")
                    light_data.energy = 2.5
                    light_data.angle = math.radians(3.0)
                    key_light = bpy.data.objects.new("InspectionSun", light_data)
                    scene.collection.objects.link(key_light)
                    created_lights.append(key_light)
                return key_light

            if include_overlays:
                mesh = bpy.data.meshes.new("InspectionBBox")
                bm = bmesh.new()
                bmesh.ops.create_cube(bm, size=1.0)
                bm.to_mesh(mesh)
                bm.free()
                overlay_obj = bpy.data.objects.new("InspectionBBox", mesh)
                scene.collection.objects.link(overlay_obj)
                overlay_obj.location = center
                overlay_obj.scale = (
                    max(extents[0], 0.001),
                    max(extents[1], 0.001),
                    max(extents[2], 0.001),
                )
                modifier = overlay_obj.modifiers.new("InspectionWireframe", "WIREFRAME")
                modifier.thickness = max(size * 0.003, 0.001)
                modifier.use_replace = True
                modifier.use_boundary = True

            def make_wireframe_copies() -> None:
                for obj in list(scene.objects):
                    if obj.type != "MESH" or obj.hide_render or obj.name.startswith("Inspection"):
                        continue
                    copy = obj.copy()
                    copy.data = obj.data.copy()
                    scene.collection.objects.link(copy)
                    modifier = copy.modifiers.new("InspectionWireframe", "WIREFRAME")
                    modifier.thickness = max(size * 0.004, 0.001)
                    modifier.use_replace = True
                    modifier.use_boundary = True
                    obj.hide_render = True
                    hidden_objects.append(obj)
                    wireframe_copies.append(copy)

            def clear_wireframe_copies() -> None:
                restore_materials()
                for copy in list(wireframe_copies):
                    data = copy.data
                    bpy.data.objects.remove(copy, do_unlink=True)
                    if data.users == 0:
                        bpy.data.meshes.remove(data)
                wireframe_copies.clear()
                for obj in hidden_objects:
                    obj.hide_render = False
                hidden_objects.clear()

            view_metadata: List[Dict[str, Any]] = []

            def render_view(view: Dict[str, Any], kind: str, filename: str) -> str:
                cam_data.type = view["camera_type"]
                if view["camera_type"] == "ORTHO":
                    cam_data.ortho_scale = view["ortho_scale"]
                else:
                    cam_data.lens = view["lens"]
                cam_obj.location = view["position"]
                cam_obj.rotation_euler = view["rotation"]
                bpy.context.view_layer.update()

                background.inputs[1].default_value = 0.35 if kind == "gray" else 0.0
                if kind == "gray":
                    light = ensure_key_light()
                    direction = (center - cam_obj.location).normalized()
                    light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

                apply_material(materials[kind])
                view_layer.material_override = None
                filepath = os.path.join(output_dir, filename)
                render.filepath = filepath
                bpy.ops.render.render(write_still=True)
                view_metadata.append({
                    "name": view["name"],
                    "label": view["label"],
                    "camera_type": view["camera_type"],
                    "location": [round(float(value), 6) for value in cam_obj.location],
                    "rotation_euler": [round(float(value), 6) for value in cam_obj.rotation_euler],
                    "ortho_scale": view["ortho_scale"],
                    "lens": view["lens"],
                    "engine": render.engine,
                    "shading": kind,
                    "overlay": bool(include_overlays),
                    "file": filepath,
                })
                return filepath

            def stitch_quad(paths: List[str]) -> str:
                quad = bpy.data.images.new(
                    "QuadView", width=resolution * 2, height=resolution * 2
                )
                pixels = [0.0] * (resolution * 2 * resolution * 2 * 4)
                for index, path in enumerate(paths):
                    loaded = bpy.data.images.load(path)
                    source = list(loaded.pixels)
                    row_offset = (1 if index < 2 else 0) * resolution
                    column_offset = (0 if index % 2 == 0 else 1) * resolution
                    row_length = resolution * 4
                    for row in range(resolution):
                        source_start = row * row_length
                        destination_start = (
                            (row_offset + row) * (resolution * 2) + column_offset
                        ) * 4
                        pixels[destination_start:destination_start + row_length] = source[
                            source_start:source_start + row_length
                        ]
                    bpy.data.images.remove(loaded)
                quad.pixels = pixels
                quad_path = os.path.join(output_dir, "quad_inspection.png")
                quad.filepath_raw = quad_path
                quad.file_format = "PNG"
                quad.save()
                bpy.data.images.remove(quad)
                return quad_path

            if mode == "quad":
                image_paths = [
                    render_view(view, "gray", f"{view['name'].lower()}.png")
                    for view in selected_views
                ]
                quad_path = stitch_quad(image_paths)
            elif mode == "wireframe":
                make_wireframe_copies()
                try:
                    quad_path = render_view(selected_views[0], "white", "wireframe.png")
                finally:
                    clear_wireframe_copies()
            else:
                quad_path = render_view(selected_views[0], shading_kind, f"{mode}.png")

            wireframe_path = None
            if show_wireframe and mode == "quad":
                make_wireframe_copies()
                try:
                    wireframe_path = render_view(views["iso"], "white", "wireframe.png")
                finally:
                    clear_wireframe_copies()

            b64_data = ""
            if return_base64 and os.path.exists(quad_path):
                import base64
                with open(quad_path, "rb") as handle:
                    b64_data = base64.b64encode(handle.read()).decode("utf-8")

            view_labels = [view["label"] for view in selected_views]
            if mode != "quad":
                view_labels = [f"{mode.upper()} inspection view"]
            metadata = {
                "render_id": render_id,
                "mode": mode,
                "resolution": [resolution, resolution],
                "views": view_metadata,
                "background": {
                    "engine": "world",
                    "color": [0.02, 0.02, 0.02],
                    "strength": 0.35 if shading_kind == "gray" else 0.0,
                },
                "assembly_world_aabb": aabb,
                "units": audit.get("dimensions", {}).get("units", {}),
                "overlays": {
                    "bounding_box": bool(include_overlays),
                    "dimensions": "metadata" if include_overlays else False,
                    "anchors": False,
                    "contacts": False,
                    "collisions": False,
                },
                "deterministic_settings": True,
                "pixel_identity": "same_blender_build_and_gpu",
                "blender_version": bpy.app.version_string,
                "output_dir": output_dir,
            }

            result = {
                "success": True,
                "audit": audit,
                "quad_image_path": quad_path,
                "image_path": quad_path,
                "views": view_labels,
                "labels": view_labels,
                "axis_legend": {"X": "red", "Y": "green", "Z": "blue"},
                "flagged_objects": sorted(set(
                    re.findall(r"'([^']+)'", " ".join(audit.get("critical_issues", [])))
                )),
                "metadata": metadata,
            }
            if wireframe_path:
                result["wireframe_image_path"] = wireframe_path
            if b64_data:
                result["image_data"] = b64_data
            return result
        finally:
            if view_layer:
                view_layer.material_override = old_state["material_override"]
            restore_materials()
            for copy in list(wireframe_copies):
                data = copy.data
                bpy.data.objects.remove(copy, do_unlink=True)
                if data.users == 0:
                    bpy.data.meshes.remove(data)
            for obj in hidden_objects:
                obj.hide_render = False
            for obj in hidden_lights:
                obj.hide_render = False
            for obj in created_lights:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.lights.remove(data)
            for material in created_materials:
                if material.users == 0:
                    bpy.data.materials.remove(material)
            if overlay_obj is not None:
                data = overlay_obj.data
                bpy.data.objects.remove(overlay_obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.meshes.remove(data)
            scene.world = old_state["world"]
            if inspection_world is not None and inspection_world.users == 0:
                bpy.data.worlds.remove(inspection_world)
            scene.camera = old_state["camera"]
            render.engine = old_state["engine"]
            render.resolution_x = old_state["resolution_x"]
            render.resolution_y = old_state["resolution_y"]
            render.resolution_percentage = old_state["resolution_percentage"]
            render.film_transparent = old_state["film_transparent"]
            render.filepath = old_state["filepath"]
            render.image_settings.file_format = old_state["file_format"]
            render.image_settings.color_mode = old_state["color_mode"]
            render.image_settings.compression = old_state["compression"]
            with suppress(Exception):
                scene.view_settings.view_transform = old_state["view_transform"]
                scene.view_settings.look = old_state["look"]
                scene.view_settings.exposure = old_state["exposure"]
                scene.view_settings.gamma = old_state["gamma"]
            if old_state["eevee_samples"] is not None:
                scene.eevee.taa_render_samples = old_state["eevee_samples"]
            if cam_obj is not None:
                bpy.data.objects.remove(cam_obj, do_unlink=True)
            if cam_data is not None and cam_data.users == 0:
                bpy.data.cameras.remove(cam_data)

    def setup_studio_lighting(self, intensity_multiplier: float = 1.0, confirm: bool = False) -> Dict[str, Any]:
        """Crea un esquema de iluminación de estudio de 3 puntos (Key, Fill, Rim)."""
        existing_lights = [o.name for o in bpy.context.scene.objects if o.type == "LIGHT"]
        dry = self._confirm_or_dry_run("setup_studio_lighting", confirm, {
            "remove_lights": existing_lights,
            "create_lights": ["Key_Light", "Fill_Light", "Rim_Light"],
        })
        if dry:
            return dry

        for o in list(bpy.context.scene.objects):
            if o.type == "LIGHT":
                bpy.data.objects.remove(o, do_unlink=True)

        lights = [
            ("Key_Light", [2.5, -2.5, 3.5], 600.0 * intensity_multiplier, [1.0, 0.98, 0.95]),
            ("Fill_Light", [-3.0, -1.5, 2.0], 250.0 * intensity_multiplier, [0.90, 0.95, 1.0]),
            ("Rim_Light", [0.0, 3.0, 3.0], 450.0 * intensity_multiplier, [1.0, 1.0, 1.0]),
        ]

        created = []
        for l_name, loc, power, col in lights:
            ld = bpy.data.lights.new(name=l_name, type="POINT")
            ld.energy = power
            ld.color = col
            lo = bpy.data.objects.new(name=l_name, object_data=ld)
            lo.location = Vector(loc)
            bpy.context.collection.objects.link(lo)
            created.append(lo.name)

        return {"success": True, "lights": created}

    # ==========================================================================
    # 8. TRANSFORMS, MATERIALS & CHECKPOINTS
    # ==========================================================================
    def transform_object(
        self,
        name: str,
        location: Optional[List[float]] = None,
        rotation_deg: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
        dimensions: Optional[List[float]] = None,
        apply_scale: bool = True,
    ) -> Dict[str, Any]:
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")

        if location is not None:
            obj.location = Vector(location)
        if rotation_deg is not None:
            obj.rotation_euler = Euler((math.radians(c) for c in rotation_deg), "XYZ")
        if scale is not None:
            obj.scale = Vector(scale)
        if dimensions is not None and obj.type == "MESH":
            obj.dimensions = Vector(dimensions)

        bpy.context.view_layer.update()
        if apply_scale and obj.type == "MESH":
            self.repair_mesh_geometry(object_names=[obj.name], apply_scale=True)

        return {"success": True, "object": obj.name, "world_aabb": self._get_aabb(obj) if obj.type == "MESH" else None}

    def delete_object(self, name: str, confirm: bool = False) -> Dict[str, Any]:
        obj = bpy.data.objects.get(name)
        if not obj:
            return {"success": False, "message": f"Object '{name}' not found"}
        dry = self._confirm_or_dry_run("delete_object", confirm, {"object": obj.name, "type": obj.type})
        if dry:
            return dry
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"success": True, "deleted": name}

    def duplicate_object(
        self,
        name: str,
        new_name: Optional[str] = None,
        location: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        dup_obj = obj.copy()
        if obj.data:
            dup_obj.data = obj.data.copy()
        dup_obj.name = new_name or f"{obj.name}_Copy"
        bpy.context.collection.objects.link(dup_obj)
        if location:
            dup_obj.location = Vector(location)
        return {"success": True, "original": obj.name, "duplicate": dup_obj.name}

    def create_material(
        self,
        name: str,
        color: Optional[List[float]] = None,
        metallic: float = 0.0,
        roughness: float = 0.45,
        emission: Optional[List[float]] = None,
        alpha: float = 1.0,
    ) -> Dict[str, Any]:
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF") or nodes.new(type="ShaderNodeBsdfPrincipled")

        if color:
            c = list(color) if len(color) == 4 else list(color) + [1.0]
            bsdf.inputs["Base Color"].default_value = c
        bsdf.inputs["Metallic"].default_value = float(metallic)
        bsdf.inputs["Roughness"].default_value = float(roughness)
        if alpha < 1.0:
            bsdf.inputs["Alpha"].default_value = float(alpha)
            mat.blend_method = "BLEND"
        if emission and "Emission Color" in bsdf.inputs:
            e = list(emission) if len(emission) == 4 else list(emission) + [1.0]
            bsdf.inputs["Emission Color"].default_value = e

        return {"success": True, "material": mat.name}

    def assign_material(self, object_name: str, material_name: str) -> Dict[str, Any]:
        obj = bpy.data.objects.get(object_name)
        mat = bpy.data.materials.get(material_name)
        if not obj or not mat:
            raise ValueError(f"Object '{object_name}' or Material '{material_name}' missing")

        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        return {"success": True, "object": obj.name, "assigned_material": mat.name}

    def clear_scene(self, keep_cameras_and_lights: bool = False, confirm: bool = False) -> Dict[str, Any]:
        targets = [
            obj.name
            for obj in bpy.context.scene.objects
            if not (keep_cameras_and_lights and obj.type in ("CAMERA", "LIGHT"))
        ]
        dry = self._confirm_or_dry_run("clear_scene", confirm, {"objects": targets})
        if dry:
            return dry

        count = 0
        for obj in list(bpy.context.scene.objects):
            if keep_cameras_and_lights and obj.type in ("CAMERA", "LIGHT"):
                continue
            bpy.data.objects.remove(obj, do_unlink=True)
            count += 1
        return {"success": True, "removed_count": count}

    def _validate_export(self, profile: str) -> Dict[str, Any]:
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
        errors: List[Dict[str, Any]] = []
        warnings: List[str] = []
        if not meshes:
            errors.append({
                "rule": "mesh_objects",
                "expected": ">=1",
                "actual": 0,
                "method": "scene_inventory",
            })
        material_names = set()
        uv_objects = 0
        for obj in meshes:
            absolute_scale = [abs(float(value)) for value in obj.scale]
            if any(value <= 1e-6 for value in absolute_scale):
                errors.append({
                    "rule": "zero_scale",
                    "object": obj.name,
                    "expected": ">0",
                    "actual": [round(float(value), 6) for value in obj.scale],
                    "method": "object_scale",
                })
            if len({round(value, 4) for value in absolute_scale}) > 1:
                errors.append({
                    "rule": "non_uniform_scale",
                    "object": obj.name,
                    "expected": "uniform |scale|",
                    "actual": [round(float(value), 6) for value in obj.scale],
                    "method": "object_scale",
                })
            if any(abs(value - 1.0) > 1e-4 for value in absolute_scale):
                warnings.append(
                    f"UNAPPLIED_SCALE {obj.name}: "
                    f"{[round(float(value), 6) for value in obj.scale]}"
                )
            if obj.data.uv_layers:
                uv_objects += 1
            else:
                warnings.append(f"NO_UV {obj.name}")
            if not obj.data.materials:
                warnings.append(f"NO_MATERIAL {obj.name}")
            for slot in obj.material_slots:
                material = slot.material
                if not material:
                    continue
                material_names.add(material.name)
                if not material.use_nodes:
                    continue
                for node in material.node_tree.nodes:
                    if (
                        node.type == "TEX_IMAGE"
                        and node.image
                        and not node.image.filepath
                        and not node.image.packed_file
                    ):
                        warnings.append(
                            f"MISSING_TEXTURE {obj.name}/{material.name}"
                        )

        lod_objects = sorted(
            obj.name
            for obj in meshes
            if "_lod" in obj.name.lower() or re.search(r"_LOD\d", obj.name, re.IGNORECASE)
        )
        collision_objects = sorted(
            obj.name
            for obj in meshes
            if "colonly" in obj.name.lower()
            or obj.name.lower().startswith("ucx_")
            or "_collision" in obj.name.lower()
        )
        if not lod_objects:
            warnings.append("NO_LOD_OBJECTS")
        if not collision_objects:
            warnings.append("NO_COLLISION_OBJECTS")
        if not armatures:
            warnings.append("NO_SKELETON")
        if armatures and not bpy.data.actions:
            warnings.append("NO_ANIMATIONS")

        checks = {
            "mesh_objects": len(meshes),
            "materials": sorted(material_names),
            "uv_objects": uv_objects,
            "armatures": len(armatures),
            "actions": len(bpy.data.actions),
            "lod_objects": lod_objects,
            "collision_objects": collision_objects,
            "profile": profile,
        }
        return {
            "passed": not errors,
            "profile": profile,
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
        }

    def _reimport_check(self, path: str, fmt: str, profile: str) -> Dict[str, Any]:
        if fmt not in ("GLB", "GLTF", "FBX"):
            return {"checked": False, "reason": f"no importer for {fmt}"}

        before_objects = set(bpy.data.objects)
        before_actions = set(bpy.data.actions)
        before_active = bpy.context.view_layer.objects.active
        source_aabb = None
        source_dimensions = None
        import_scale = 1.0
        try:
            source_meshes = [
                obj for obj in bpy.context.scene.objects if obj.type == "MESH"
            ]
            if source_meshes:
                minimum = [float("inf")] * 3
                maximum = [float("-inf")] * 3
                for obj in source_meshes:
                    snapshot = GeometryService.snapshot(obj)
                    for axis in range(3):
                        minimum[axis] = min(minimum[axis], snapshot.world_aabb[0][axis])
                        maximum[axis] = max(maximum[axis], snapshot.world_aabb[1][axis])
                source_aabb = [minimum, maximum]

            try:
                if fmt in ("GLB", "GLTF"):
                    bpy.ops.import_scene.gltf(filepath=path)
                else:
                    import_scale = 0.01 if profile == "unreal" else 1.0
                    bpy.ops.import_scene.fbx(filepath=path, global_scale=import_scale)
            except Exception as exc:
                return {
                    "checked": False,
                    "reason": f"importer failed: {type(exc).__name__}: {exc}",
                }

            new_objects = [obj for obj in bpy.data.objects if obj not in before_objects]
            new_meshes = [obj for obj in new_objects if obj.type == "MESH"]
            if not new_meshes:
                return {
                    "checked": True,
                    "passed": False,
                    "reason": "no meshes reimported",
                }

            minimum = [float("inf")] * 3
            maximum = [float("-inf")] * 3
            for obj in new_meshes:
                snapshot = GeometryService.snapshot(obj)
                for axis in range(3):
                    minimum[axis] = min(minimum[axis], snapshot.world_aabb[0][axis])
                    maximum[axis] = max(maximum[axis], snapshot.world_aabb[1][axis])
            dimensions = [
                maximum[axis] - minimum[axis]
                for axis in range(3)
            ]
            delta = None
            tolerance = None
            if source_aabb is not None:
                source_dimensions = [
                    source_aabb[1][axis] - source_aabb[0][axis]
                    for axis in range(3)
                ]
                delta = max(
                    abs(dimensions[axis] - source_dimensions[axis])
                    for axis in range(3)
                )
                tolerance = max(0.01, max(source_dimensions) * 0.01)
            materials = len({
                slot.material.name
                for obj in new_meshes
                for slot in obj.material_slots
                if slot.material
            })
            armatures = len([obj for obj in new_objects if obj.type == "ARMATURE"])
            new_actions = [
                action for action in bpy.data.actions if action not in before_actions
            ]
            passed = delta is not None and tolerance is not None and delta <= tolerance
            return {
                "checked": True,
                "passed": passed,
                "objects": len(new_objects),
                "meshes": len(new_meshes),
                "materials": materials,
                "armatures": armatures,
                "actions": len(new_actions),
                "dimensions": [round(float(value), 6) for value in dimensions],
                "source_dimensions": (
                    [round(float(value), 6) for value in source_dimensions]
                    if source_aabb is not None
                    else None
                ),
                "dimension_delta": round(float(delta), 6) if delta is not None else None,
                "tolerance": round(float(tolerance), 6) if tolerance is not None else None,
                "import_scale": import_scale,
            }
        finally:
            for obj in [item for item in bpy.data.objects if item not in before_objects]:
                data = obj.data
                obj_type = obj.type
                bpy.data.objects.remove(obj, do_unlink=True)
                if data is not None and data.users == 0:
                    if obj_type == "MESH":
                        bpy.data.meshes.remove(data)
                    elif obj_type == "ARMATURE":
                        bpy.data.armatures.remove(data)
            for action in [item for item in bpy.data.actions if item not in before_actions]:
                with suppress(Exception):
                    bpy.data.actions.remove(action)
            for mesh in [item for item in bpy.data.meshes if item.users == 0]:
                bpy.data.meshes.remove(mesh)
            for material in [item for item in bpy.data.materials if item.users == 0]:
                bpy.data.materials.remove(material)
            bpy.context.view_layer.objects.active = before_active

    def export_scene(
        self,
        filepath: str,
        format: Optional[str] = None,
        profile: str = "generic-gltf",
        force: bool = False,
        verify_reimport: bool = True,
    ) -> Dict[str, Any]:
        """Export with a game profile, validate the scene and reimport when possible."""
        profile_key = str(profile).strip().lower().replace("_", "-")
        profiles = {
            "godot": {"formats": ("GLB", "GLTF"), "default": "GLB"},
            "unity": {"formats": ("GLB", "GLTF"), "default": "GLB"},
            "unreal": {"formats": ("FBX",), "default": "FBX"},
            "generic-gltf": {"formats": ("GLB", "GLTF", "OBJ"), "default": "GLB"},
        }
        if profile_key not in profiles:
            raise ValueError(
                f"Unsupported export profile '{profile}'. Valid: {sorted(profiles)}"
            )
        fmt = str(format).upper() if format else profiles[profile_key]["default"]
        if fmt not in profiles[profile_key]["formats"]:
            raise ValueError(
                f"Profile '{profile_key}' supports {profiles[profile_key]['formats']}; "
                f"got '{fmt}'."
            )

        allowed = {
            "GLB": {".glb"},
            "GLTF": {".gltf"},
            "FBX": {".fbx"},
            "OBJ": {".obj"},
        }
        path = resolve_output_path(filepath, allowed[fmt])
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        validation = self._validate_export(profile_key)
        if not validation["passed"] and not force:
            return {
                "success": False,
                "filepath": path,
                "format": fmt,
                "profile": profile_key,
                "validation": validation,
            }

        if fmt in ("GLB", "GLTF"):
            bpy.ops.export_scene.gltf(
                filepath=path,
                export_format="GLB" if fmt == "GLB" else "GLTF_SEPARATE",
                export_apply=True,
                export_yup=True,
                export_normals=True,
                export_tangents=True,
                export_texcoords=True,
                export_materials="EXPORT",
                export_animations=True,
                export_skins=True,
                export_lights=False,
                export_cameras=False,
                export_extras=True,
            )
        elif fmt == "FBX":
            bpy.ops.export_scene.fbx(
                filepath=path,
                use_selection=False,
                apply_scale_options="FBX_SCALE_ALL",
                global_scale=100.0 if profile_key == "unreal" else 1.0,
                axis_forward="-Z",
                axis_up="Y",
                bake_anim=True,
                add_leaf_bones=False,
                use_mesh_modifiers=True,
            )
        elif fmt == "OBJ":
            bpy.ops.wm.obj_export(filepath=path)

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return {
                "success": False,
                "filepath": path,
                "format": fmt,
                "profile": profile_key,
                "validation": validation,
                "error": "export did not write a file",
            }

        reimport = (
            self._reimport_check(path, fmt, profile_key)
            if verify_reimport
            else {"checked": False, "reason": "disabled"}
        )
        return {
            "success": True,
            "filepath": path,
            "format": fmt,
            "profile": profile_key,
            "file_size": os.path.getsize(path),
            "validation": validation,
            "reimport": reimport,
        }

    def execute_code(self, code: str, auto_audit: bool = True, blueprint_name: Optional[str] = None) -> Dict[str, Any]:
        if not self._execute_code_allowed():
            raise PermissionError(
                "execute_code is disabled. Enable 'Allow execute_code' in the Blender MCP Pro "
                f"preferences or set {EXECUTE_CODE_ENV_VAR}=1."
            )
        local_scope = {"bpy": bpy, "bmesh": bmesh, "Vector": Vector, "Matrix": Matrix, "Euler": Euler}
        exec(code, local_scope)
        bpy.context.view_layer.update()
        res = {"success": True}
        if auto_audit:
            res["auto_audit"] = self.audit_3d_model(blueprint_name=blueprint_name)
        return res

    def _execute_code_allowed(self) -> bool:
        if os.environ.get(EXECUTE_CODE_ENV_VAR) == "1":
            return True
        addon = bpy.context.preferences.addons.get(ADDON_PACKAGE)
        return bool(addon and getattr(addon.preferences, "allow_execute_code", False))

    def _confirm_or_dry_run(self, operation: str, confirm: bool, details: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a dry-run payload unless the caller confirmed the operation."""
        if confirm or os.environ.get(ALLOW_UNSAFE_OPS_ENV_VAR) == "1":
            return None
        return {
            "success": False,
            "dry_run": True,
            "requires_confirmation": True,
            "operation": operation,
            "message": f"Re-run with confirm=true to execute {operation}.",
            "details": details,
        }

    def create_checkpoint(self, name: str = "step", max_checkpoints: int = 10) -> Dict[str, Any]:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name or "step"))
        cp_path = osp.join(self.checkpoint_dir, f"cp_{safe_name}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=cp_path, copy=True)
        self.checkpoints[safe_name] = {
            "name": safe_name,
            "filepath": cp_path,
            "timestamp": time.time(),
            "object_count": len(bpy.context.scene.objects),
        }
        if len(self.checkpoints) > max_checkpoints:
            oldest_key = min(self.checkpoints.keys(), key=lambda k: self.checkpoints[k]["timestamp"])
            old_cp = self.checkpoints.pop(oldest_key, None)
            if old_cp and osp.exists(old_cp["filepath"]):
                with suppress(Exception):
                    os.unlink(old_cp["filepath"])
        return {"success": True, "checkpoint": self.checkpoints[safe_name]}

    def rollback_checkpoint(self, name: str = "step", confirm: bool = False) -> Dict[str, Any]:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name or "step"))
        cp = self.checkpoints.get(safe_name)
        if not cp or not osp.exists(cp["filepath"]):
            return {"error": f"Checkpoint '{safe_name}' not found. Available: {list(self.checkpoints.keys())}"}
        dry = self._confirm_or_dry_run("rollback_checkpoint", confirm, {
            "checkpoint": safe_name,
            "filepath": cp["filepath"],
            "object_count": cp.get("object_count"),
            "warning": "Unsaved changes in the current file will be lost.",
        })
        if dry:
            return dry
        bpy.ops.wm.open_mainfile(filepath=cp["filepath"])
        with suppress(Exception):
            bpy.context.scene.blendermcp_server_running = self.running
            bpy.types.blendermcp_server = self
        return {"success": True, "restored_checkpoint": safe_name, "scene_info": self.get_scene_info()}

    def list_checkpoints(self) -> Dict[str, Any]:
        return {"checkpoints": list(self.checkpoints.values())}

    # ==========================================================================
    # 10. ADVANCED MVP TOOLS (raycast seating, polish, smart materials, game-ready, PT datacenter)
    # ==========================================================================
    def place_on_surface_raycast(
        self,
        object_name: str,
        target_surface: str,
        uv_ratio: Optional[List[float]] = None,
        align_to_normal: bool = True,
        embed_depth: float = 0.003,
    ) -> Dict[str, Any]:
        """Seat object_name on target_surface via an AABB-seeded BVHTree raycast, aligning local Z to the hit normal."""
        obj = bpy.data.objects.get(object_name)
        tgt = bpy.data.objects.get(target_surface)
        if not obj or not tgt:
            raise ValueError(f"Objects '{object_name}' and '{target_surface}' must exist")
        if obj.type != "MESH" or tgt.type != "MESH":
            raise TypeError("place_on_surface_raycast needs MESH objects")
        uv = uv_ratio or [0.5, 0.5]
        u = min(max(float(uv[0]), 0.0), 1.0)
        v = min(max(float(uv[1]), 0.0), 1.0)

        aabb = self._get_aabb(tgt)
        (mnx, mny, mnz), (mxx, mxy, mxz) = aabb
        span = max(mxx - mnx, mxy - mny, mxz - mnz, 0.5)
        start = Vector((mnx + (mxx - mnx) * u, mny + (mxy - mny) * v, mxz + span + 1.0))
        bvh, _, _ = self._build_world_bvh(tgt)
        hit_loc, hit_nor, _idx, _dist = bvh.ray_cast(start, Vector((0.0, 0.0, -1.0)))

        # Rayo fallido: apoyar sobre el punto AABB como fallback.
        fallback_used = hit_loc is None
        impact = Vector(tuple(hit_loc)) if not fallback_used else Vector((start.x, start.y, mxz))
        n_raw = Vector(tuple(hit_nor)) if not fallback_used else Vector((0.0, 0.0, 1.0))
        normal = n_raw.normalized() if n_raw.length > 1e-6 else Vector((0.0, 0.0, 1.0))

        # Primero orientar (cambia el AABB), luego asentar la base sobre el impacto.
        if align_to_normal:
            quat = Vector((0.0, 0.0, 1.0)).rotation_difference(normal)
            if obj.rotation_mode == "QUATERNION":
                obj.rotation_quaternion = (obj.parent.matrix_world.to_quaternion().inverted() @ quat) if obj.parent else quat
            else:
                local_quat = (obj.parent.matrix_world.to_quaternion().inverted() @ quat) if obj.parent else quat
                obj.rotation_euler = local_quat.to_euler()
            bpy.context.view_layer.update()

        obj_aabb = self._get_aabb(obj)
        world_delta = (impact - Vector(obj_aabb[0])) - normal * float(embed_depth)
        if obj.parent:
            # location es local: el delta de mundo se convierte al padre.
            inv_rot = obj.parent.matrix_world.inverted().to_3x3()
            obj.location += inv_rot @ world_delta
        else:
            obj.location += world_delta
        bpy.context.view_layer.update()

        return {
            "success": True,
            "object": obj.name,
            "target": tgt.name,
            "impact_point": [round(c, 5) for c in impact],
            "surface_normal": [round(c, 5) for c in normal],
            "fallback_used": fallback_used,
            "final_world_aabb": self._get_aabb(obj),
        }

    @staticmethod
    def _new_shader_node(nodes: bpy.types.Nodes, modern: str, legacy: Optional[str] = None) -> bpy.types.Node:
        """Crea un nodo de shader eligiendo el id según la versión de Blender.

        Evita el fallo tardío de un bl_idname inexistente (como pasó con el
        nodo Geometry): si ninguno existe, el ValueError lista qué se probó.
        """
        candidates = [modern] + ([legacy] if legacy and legacy != modern else [])
        if tuple(bpy.app.version[:2]) < (4, 0):
            candidates = list(reversed(candidates)) or candidates
        tried = []
        for type_id in candidates:
            tried.append(type_id)
            with suppress(Exception):
                return nodes.new(type=type_id)
        raise ValueError(f"Nodo shader no disponible en Blender {bpy.app.version_string}: probé {tried}.")

    def smart_bevel_and_polish(
        self,
        object_names: Optional[List[str]] = None,
        profile: str = "HARD_SURFACE",
    ) -> Dict[str, Any]:
        """Repair, bevel (harden normals + clamp overlap) and angle-autosmooth meshes per profile."""
        key = str(profile).upper()
        if key not in SMART_BEVEL_PROFILES:
            raise ValueError(f"Unknown profile '{profile}'. Valid: {sorted(SMART_BEVEL_PROFILES)}")
        cfg = SMART_BEVEL_PROFILES[key]
        self.repair_mesh_geometry(object_names=object_names, apply_scale=True)

        objs = [bpy.data.objects.get(n) for n in object_names] if object_names else list(bpy.context.scene.objects)
        processed = []
        details = []
        for obj in objs:
            if not obj or obj.type != "MESH" or not obj.data:
                continue
            for mod in [m for m in obj.modifiers if m.name == "Polish_Bevel"]:
                obj.modifiers.remove(mod)
            bev = obj.modifiers.new(name="Polish_Bevel", type="BEVEL")
            bev.segments = int(cfg["segments"])
            bev.limit_method = "ANGLE"
            bev.angle_limit = math.radians(float(cfg["angle_deg"]))
            bev.harden_normals = True
            with suppress(Exception):  # nombre del flag varía según versión
                bev.use_clamp_overlap = True
            mesh = obj.data
            autosmooth = "legacy"
            if hasattr(mesh, "use_auto_smooth"):  # Blender < 4.1
                mesh.use_auto_smooth = True
                mesh.auto_smooth_angle = math.radians(float(cfg["angle_deg"]))
            else:  # Blender >= 4.1: sin auto_smooth, Weighted Normal da el sombreado equivalente
                for mod in [m for m in obj.modifiers if m.name == "Polish_WeightedNormal"]:
                    obj.modifiers.remove(mod)
                wn = obj.modifiers.new(name="Polish_WeightedNormal", type="WEIGHTED_NORMAL")
                with suppress(Exception):
                    wn.keep_sharp = True
                autosmooth = "weighted_normal"
            if cfg["smooth"]:
                for p in mesh.polygons:
                    p.use_smooth = True
            processed.append(obj.name)
            details.append({"object": obj.name, "autosmooth": autosmooth})

        return {"success": True, "profile": key, "processed": processed,
                "processed_details": details}

    def apply_smart_procedural_material(
        self,
        object_name: str,
        preset: str,
        primary_color: Optional[List[float]] = None,
        wear_amount: float = 0.2,
        scale: float = 5.0,
    ) -> Dict[str, Any]:
        """Build a Principled + Noise/Bump + Bevel-Pointiness edge-wear material from a preset and assign it."""
        key = str(preset).upper()
        if key not in SMART_MATERIAL_PRESETS:
            raise ValueError(f"Unknown preset '{preset}'. Valid: {sorted(SMART_MATERIAL_PRESETS)}")
        obj = bpy.data.objects.get(object_name)
        if not obj or obj.type != "MESH":
            raise ValueError(f"Object '{object_name}' must be an existing MESH")
        cfg = SMART_MATERIAL_PRESETS[key]
        w = min(max(float(wear_amount), 0.0), 1.0)

        mat = bpy.data.materials.get(f"{obj.name}_{key}") or bpy.data.materials.new(name=f"{obj.name}_{key}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        out = nodes.new(type="ShaderNodeOutputMaterial")
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        base = list(primary_color) if primary_color else list(cfg["color"])
        base = base if len(base) == 4 else base + [1.0]
        for inp, val in (("Base Color", base), ("Metallic", float(cfg.get("metallic", 0.0))),
                         ("Roughness", float(cfg.get("roughness", 0.5))),
                         ("Transmission", float(cfg.get("transmission", 0.0))),
                         ("Alpha", float(cfg.get("alpha", 1.0)))):
            if inp in bsdf.inputs:
                bsdf.inputs[inp].default_value = val
        if float(cfg.get("alpha", 1.0)) < 1.0:
            mat.blend_method = "BLEND"

        # Variación de superficie: Noise -> Bump -> Normal.
        if float(cfg.get("bump_strength", 0.0)) > 0.0:
            noise = nodes.new(type="ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = float(scale)
            bump = nodes.new(type="ShaderNodeBump")
            bump.inputs["Strength"].default_value = float(cfg["bump_strength"])
            links.new(noise.outputs["Fac"], bump.inputs["Height"])
            if "Normal" in bsdf.inputs:
                links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

        # Desgaste de bordes: Pointiness -> Ramp -> Mix(Base, Wear) con factor wear_amount.
        # ShaderNodeMixRGB está deprecado en Blender 4.x: se usa ShaderNodeMix
        # (sockets Factor/A/B/Result) cuando bpy.app.version >= 4.0.
        # El nodo Geometry se llama ShaderNodeNewGeometry en 3.x y 4.x.
        geo = self._new_shader_node(nodes, "ShaderNodeNewGeometry")
        ramp = nodes.new(type="ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.55
        ramp.color_ramp.elements[1].position = 0.95
        if tuple(bpy.app.version[:2]) >= (4, 0):
            mix = self._new_shader_node(nodes, "ShaderNodeMix", "ShaderNodeMixRGB")
            mix.data_type = "RGBA"
            fac_in, a_in, b_in, mix_out = "Factor", "A", "B", "Result"
        else:
            mix = self._new_shader_node(nodes, "ShaderNodeMixRGB", "ShaderNodeMix")
            mix.blend_type = "MIX"
            fac_in, a_in, b_in, mix_out = "Fac", "Color1", "Color2", "Color"
        mix.inputs[a_in].default_value = base
        mix.inputs[b_in].default_value = cfg["wear_color"]
        links.new(geo.outputs["Pointiness"], ramp.inputs["Fac"])
        # La rampa sale como color: RGBToBW la lleva a factor de forma
        # type-safe en ambas versiones. Con w == 0.0 el desgaste queda
        # apagado por default, sin links redundantes.
        mix.inputs[fac_in].default_value = 0.0
        if w > 0.0:
            bw = nodes.new(type="ShaderNodeRGBToBW")
            links.new(ramp.outputs["Color"], bw.inputs["Color"])
            math_n = nodes.new(type="ShaderNodeMath")
            math_n.operation = "MULTIPLY"
            math_n.inputs[1].default_value = w
            links.new(bw.outputs["Val"], math_n.inputs[0])
            links.new(math_n.outputs["Value"], mix.inputs[fac_in])
        links.new(mix.outputs[mix_out], bsdf.inputs["Base Color"])
        # Normales redondeadas del nodo Bevel hacia el Principled.
        bevel_n = nodes.new(type="ShaderNodeBevel")
        if "Normal" in bsdf.inputs and float(cfg.get("bump_strength", 0.0)) == 0.0:
            links.new(bevel_n.outputs["Normal"], bsdf.inputs["Normal"])

        self.assign_material(object_name, mat.name)
        return {"success": True, "object": obj.name, "material": mat.name, "preset": key, "wear_amount": w}

    def generate_game_ready_asset(
        self,
        object_names: Optional[List[str]] = None,
        target_engine: str = "GODOT",
        generate_collision_hull: bool = True,
        max_tris: int = 10000,
    ) -> Dict[str, Any]:
        """Normalize scales, ground, decimate over budget, add convex hulls and re-audit. No file export."""
        self.repair_mesh_geometry(object_names=object_names, apply_scale=True)
        self.ground_model(object_names=object_names, center_xy=True)

        objs = [bpy.data.objects.get(n) for n in object_names] if object_names else list(bpy.context.scene.objects)
        mesh_objs = [o for o in objs if o and o.type == "MESH" and o.data and len(o.data.polygons) > 0]
        if not mesh_objs:
            raise ValueError("generate_game_ready_asset found no mesh objects")

        def _tri_count(o) -> int:
            return sum(max(0, len(p.vertices) - 2) for p in o.data.polygons)

        total_before = sum(_tri_count(o) for o in mesh_objs)
        decimated, decimate_pending, ratio = [], [], 1.0
        if total_before > int(max_tris):
            ratio = max(0.1, float(max_tris) / float(total_before))
            for o in mesh_objs:
                dec = o.modifiers.new(name="GameDecimate", type="DECIMATE")
                dec.ratio = ratio
                dec.use_collapse_triangulate = True
                try:
                    bpy.context.view_layer.objects.active = o
                    bpy.ops.object.modifier_apply(modifier=dec.name)
                    decimated.append(o.name)
                except Exception:
                    # Sin aplicar: el modificador queda vivo (igual exporta
                    # evaluado) pero se reporta como pendiente, no aplicado.
                    decimate_pending.append(o.name)
            total_after = sum(_tri_count(o) for o in mesh_objs)
        else:
            total_after = total_before

        hulls = []
        if generate_collision_hull:
            for o in mesh_objs:
                hull = o.copy()
                hull.data = o.data.copy()
                hull.name = f"{o.name}_colonly"
                bpy.context.collection.objects.link(hull)
                # El hull envuelve el arte en mundo: hereda el world matrix
                # del original sin doble transform por parentesco.
                hull.parent = None
                hull.matrix_world = o.matrix_world.copy()
                for mod in list(hull.modifiers):  # el hull parte de la malla base
                    hull.modifiers.remove(mod)
                bm = bmesh.new()
                bm.from_mesh(hull.data)
                res = bmesh.ops.convex_hull(bm, input=list(bm.verts))
                keep = {e for e in res["geom"] if isinstance(e, bmesh.types.BMVert)}
                bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
                bm.to_mesh(hull.data)
                bm.free()
                hull.hide_render = True
                hulls.append(hull.name)
            bpy.context.view_layer.update()

        # Re-auditar solo el arte visual (los hulls _colonly son volúmenes auxiliares).
        audit = self.audit_3d_model(object_names=[o.name for o in mesh_objs])
        return {
            "success": True,
            "engine": str(target_engine).upper(),
            "assets": [o.name for o in mesh_objs],
            "total_tris_before": total_before,
            "total_tris_after": total_after,
            "decimate_ratio": round(ratio, 4),
            "decimated": decimated,
            "decimate_pending": decimate_pending,
            "collision_hulls": hulls,
            "audit": audit,
            "export_hint": f"Ready for '{str(target_engine).upper()}': call export_scene(filepath='...glb', format='GLB')",
        }

    def build_3d_network_datacenter_from_pt(
        self,
        pt_topology_json: Any,
    ) -> Dict[str, Any]:
        """Build a cutaway datacenter room from a Packet Tracer TopologyPlan JSON: racks, desks+PCs, colored cables."""
        try:
            topo = json.loads(pt_topology_json) if isinstance(pt_topology_json, str) else dict(pt_topology_json)
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as ex:
            raise ValueError(f"Invalid pt_topology_json: not parseable JSON ({ex})")
        devices = topo.get("devices", [])
        links = topo.get("links", [])
        if not isinstance(devices, list) or len(devices) == 0:
            raise ValueError("Invalid topology: 'devices' is empty or missing; nothing to build")

        racks = [d for d in devices if str(d.get("category", "")).lower() in PT_RACK_CATEGORIES]
        hosts = [d for d in devices if d not in racks]
        room_w = max(6.0, 2.2 * max(len(racks), len(hosts), 1) + 2.0)
        room_d, wall_h = 8.0, 1.1

        # Sala en corte: piso + 4 muros bajos.
        self.create_parametric_part(name="DC_Floor", shape="BOX", dimensions=[room_w, room_d, 0.1], location=[0, 0, -0.05], origin="CENTER", bevel_width=0.0, color=[0.25, 0.26, 0.28, 1.0])
        for wname, dims, loc in [
            ("DC_Wall_N", [room_w, 0.15, wall_h], [0, room_d / 2, wall_h / 2]),
            ("DC_Wall_S", [room_w, 0.15, wall_h], [0, -room_d / 2, wall_h / 2]),
            ("DC_Wall_E", [0.15, room_d, wall_h], [room_w / 2, 0, wall_h / 2]),
            ("DC_Wall_W", [0.15, room_d, wall_h], [-room_w / 2, 0, wall_h / 2]),
        ]:
            self.create_parametric_part(name=wname, shape="BOX", dimensions=dims, location=loc, origin="CENTER", bevel_width=0.0, color=[0.55, 0.57, 0.6, 1.0])

        # LEDs emisivos compartidos para los racks.
        self.create_material(name="LED_Green", color=[0.0, 0.4, 0.0, 1.0], emission=[0.0, 1.0, 0.2, 1.0])
        self.create_material(name="LED_Amber", color=[0.4, 0.25, 0.0, 1.0], emission=[1.0, 0.6, 0.0, 1.0])

        positions: Dict[str, List[float]] = {}
        created_racks, created_hosts = [], []

        def _rack_x(i: int, n: int) -> float:
            return (i - (n - 1) / 2.0) * 2.2 if n > 1 else 0.0

        for i, dev in enumerate(racks):
            dname = re.sub(r"[^a-zA-Z0-9_-]", "_", str(dev.get("name", f"Network_{i}")))
            x = _rack_x(i, len(racks))
            rack = self.create_parametric_part(name=f"Rack_{dname}", shape="BOX", dimensions=[0.7, 0.9, 2.0], location=[x, room_d / 2 - 1.0, 0.0], origin="BOTTOM", bevel_width=0.005, color=[0.08, 0.09, 0.11, 1.0])
            created_racks.append(rack["name"])
            for l in range(4):  # LEDs frontales verdes/ámbar alternados
                led = self.create_parametric_part(name=f"Rack_{dname}_LED{l}", shape="BOX", dimensions=[0.06, 0.02, 0.06], location=[x - 0.2 + 0.13 * l, room_d / 2 - 1.0 - 0.46, 1.75], origin="CENTER", bevel_width=0.0, material_name="LED_Green" if l % 2 == 0 else "LED_Amber", parent_name=rack["name"])
            positions[str(dev.get("name"))] = [x, room_d / 2 - 1.0, 2.05]

        for i, dev in enumerate(hosts):
            dname = re.sub(r"[^a-zA-Z0-9_-]", "_", str(dev.get("name", f"Host_{i}")))
            x = _rack_x(i, len(hosts))
            desk = self.create_parametric_part(name=f"Desk_{dname}", shape="BOX", dimensions=[1.2, 0.6, 0.05], location=[x, -room_d / 2 + 1.5, 0.72], origin="CENTER", bevel_width=0.0, color=[0.5, 0.38, 0.25, 1.0])
            pc = self.create_parametric_part(name=f"PC_{dname}", shape="BOX", dimensions=[0.4, 0.35, 0.3], location=[x, -room_d / 2 + 1.5, 0.745], origin="BOTTOM", bevel_width=0.003, color=[0.12, 0.13, 0.15, 1.0], parent_name=desk["name"])
            created_hosts.append(pc["name"])
            positions[str(dev.get("name"))] = [x, -room_d / 2 + 1.5, 1.05]

        # Cableado elevado entre posiciones con color por tipo de cable PT.
        cables, warnings = [], []
        for i, link in enumerate(links if isinstance(links, list) else []):
            a, b = link.get("device_a"), link.get("device_b")
            if a not in positions or b not in positions:
                warnings.append(f"Link {a}<->{b} skipped: unknown device")
                continue
            pa, pb = positions[a], positions[b]
            top_z = max(pa[2], pb[2], 2.2)
            mid = [(pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, top_z + 0.15]
            cable_kind = str(link.get("cable", "straight")).lower()
            color = PT_CABLE_COLORS.get(cable_kind, [0.6, 0.6, 0.6, 1.0])
            cable = self.create_curve_sweep(name=f"Cable_{i}_{a}_{b}", path_points_3d=[pa, mid, pb], radius=0.02, color=color)
            cables.append(cable["name"])

        self.ground_model(center_xy=False)
        return {
            "success": True,
            "topology": topo.get("name", "datacenter"),
            "device_count": len(devices),
            "link_count": len(links) if isinstance(links, list) else 0,
            "room": ["DC_Floor", "DC_Wall_N", "DC_Wall_S", "DC_Wall_E", "DC_Wall_W"],
            "racks": created_racks,
            "hosts": created_hosts,
            "cables": cables,
            "warnings": warnings,
        }

    # ==========================================================================
    # 9. EXTERNAL ASSETS (POLY HAVEN & SKETCHFAB)
    # ==========================================================================
    def search_polyhaven_assets(self, asset_type: str = "all", categories: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {}
        if asset_type != "all":
            params["t"] = str(asset_type)
        if categories:
            params["c"] = str(categories)
        url = "https://api.polyhaven.com/assets"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = fetch_json(url, timeout=15.0)
        if not isinstance(data, dict):
            raise ValueError("Unexpected Poly Haven response")
        return [
            {
                "id": key,
                "name": value.get("name", key),
                "type": value.get("type"),
                "tags": value.get("tags", []),
            }
            for key, value in list(data.items())[:50]
            if isinstance(value, dict)
        ]

    def download_polyhaven_asset(
        self,
        asset_id: str,
        asset_type: str,
        resolution: str = "1k",
        file_format: Optional[str] = None,
    ) -> Dict[str, Any]:
        if asset_type != "hdris":
            raise NotImplementedError(f"Asset type '{asset_type}' download handling is not implemented")

        safe_id = sanitize_asset_id(asset_id, "Poly Haven asset id")
        url = f"https://api.polyhaven.com/files/{urllib.parse.quote(safe_id, safe='')}"
        file_meta = fetch_json(url, timeout=20.0)
        if not isinstance(file_meta, dict):
            raise ValueError("Unexpected Poly Haven file response")

        hdri_root = file_meta.get("hdri", {})
        if not isinstance(hdri_root, dict):
            raise ValueError("Unexpected Poly Haven HDRI metadata")
        hdri_meta = hdri_root.get(resolution, {})
        if not isinstance(hdri_meta, dict):
            raise ValueError(f"HDRI '{safe_id}' not available in {resolution}")
        hdri_info = hdri_meta.get("hdr") or hdri_meta.get("exr")
        if not isinstance(hdri_info, dict) or not hdri_info.get("url"):
            raise ValueError(f"HDRI '{safe_id}' not available in {resolution}")

        dl_url = validate_download_url(hdri_info["url"])
        suffix = os.path.splitext(urllib.parse.urlparse(dl_url).path)[1].lower()
        if suffix not in (".hdr", ".exr"):
            raise ValueError(f"Unexpected HDRI extension '{suffix}'")

        fd, tmp_hdr = tempfile.mkstemp(prefix=f"blendermcp_{safe_id}_", suffix=suffix)
        os.close(fd)
        try:
            download_to_file(dl_url, tmp_hdr, max_bytes=MAX_DOWNLOAD_BYTES, timeout=120.0)

            world = bpy.context.scene.world or bpy.data.worlds.new("World")
            bpy.context.scene.world = world
            world.use_nodes = True
            nodes = world.node_tree.nodes
            nodes.clear()
            env_tex = nodes.new(type="ShaderNodeTexEnvironment")
            env_tex.image = bpy.data.images.load(tmp_hdr)
            bg = nodes.new(type="ShaderNodeBackground")
            out = nodes.new(type="ShaderNodeOutputWorld")
            world.node_tree.links.new(env_tex.outputs["Color"], bg.inputs["Color"])
            world.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])

            with suppress(Exception):
                env_tex.image.pack()
            return {"success": True, "asset_id": safe_id, "type": "hdri", "world": world.name}
        finally:
            if osp.exists(tmp_hdr):
                with suppress(Exception):
                    os.unlink(tmp_hdr)

    def search_sketchfab_models(self, query: str, categories: Optional[str] = None, count: int = 20, downloadable: bool = True) -> List[Dict[str, Any]]:
        params = {
            "type": "models",
            "q": str(query),
            "downloadable": "true" if downloadable else "false",
        }
        if categories:
            params["categories"] = str(categories)
        url = "https://api.sketchfab.com/v3/search?" + urllib.parse.urlencode(params)
        data = fetch_json(url, timeout=20.0)
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise ValueError("Unexpected Sketchfab response")
        limit = max(1, min(int(count), 100))
        return [
            {
                "uid": item.get("uid"),
                "name": item.get("name"),
                "vertex_count": item.get("vertexCount"),
            }
            for item in results[:limit]
            if isinstance(item, dict)
        ]

    def download_sketchfab_model(self, uid: str, normalize_size: bool = True, target_size: float = 1.0) -> Dict[str, Any]:
        token = os.environ.get("SKETCHFAB_API_TOKEN", "")
        if not token:
            raise ValueError("SKETCHFAB_API_TOKEN environment variable not set")

        safe_uid = sanitize_asset_id(uid, "Sketchfab UID")
        download_url = f"https://api.sketchfab.com/v3/models/{urllib.parse.quote(safe_uid, safe='')}/download"
        data = fetch_json(
            download_url,
            timeout=30.0,
            headers={"Authorization": f"Token {token}"},
        )
        if not isinstance(data, dict):
            raise ValueError("Unexpected Sketchfab download response")
        gltf_info = data.get("gltf", {})
        gltf_url = gltf_info.get("url") if isinstance(gltf_info, dict) else None
        if not gltf_url:
            raise ValueError(f"Download URL not available for UID {safe_uid}")
        gltf_url = validate_download_url(gltf_url)

        fd, tmp_zip = tempfile.mkstemp(prefix=f"blendermcp_sketchfab_{safe_uid}_", suffix=".zip")
        os.close(fd)
        extract_dir = tempfile.mkdtemp(prefix=f"blendermcp_sketchfab_{safe_uid}_")
        try:
            download_to_file(gltf_url, tmp_zip, max_bytes=MAX_DOWNLOAD_BYTES, timeout=180.0)
            safe_extract_zip(tmp_zip, extract_dir)

            gltf_files = []
            for root, _dirs, files in os.walk(extract_dir):
                for filename in files:
                    if filename.lower().endswith((".gltf", ".glb")):
                        gltf_files.append(os.path.join(root, filename))
            if not gltf_files:
                raise FileNotFoundError("No GLTF or GLB file found in archive")

            bpy.ops.import_scene.gltf(filepath=sorted(gltf_files)[0], import_pack_images=True)
            imported = [o for o in bpy.context.selected_objects if o.type == "MESH"]
            if normalize_size and imported:
                self.ground_model(object_names=[o.name for o in imported], center_xy=True)
            return {"success": True, "uid": safe_uid, "imported_objects": [o.name for o in imported]}
        finally:
            with suppress(Exception):
                os.unlink(tmp_zip)
            shutil.rmtree(extract_dir, ignore_errors=True)


# ==============================================================================
# BLENDER UI & ADD-ON OPERATORS
# ==============================================================================
class BLENDM_OT_start_server(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Start MCP Server"

    def execute(self, context):
        server = getattr(bpy.types, "blendermcp_server", None)
        if server is None:
            server = BlenderMCPServer()
        if not server.running:
            server.start()
            if not server.running:
                self.report({"ERROR"}, "Unable to start Blender MCP Server on port 9876")
                return {"CANCELLED"}
            bpy.types.blendermcp_server = server
            context.scene.blendermcp_server_running = True
            self.report({"INFO"}, "Blender MCP Server started on port 9876")
        return {"FINISHED"}


class BLENDM_OT_stop_server(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop MCP Server"

    def execute(self, context):
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server is not None:
            bpy.types.blendermcp_server.stop()
            bpy.types.blendermcp_server = None
            context.scene.blendermcp_server_running = False
            self.report({"INFO"}, "Blender MCP Server stopped")
        return {"FINISHED"}


class BLENDM_PT_main_panel(bpy.types.Panel):
    bl_label = "Blender MCP Pro v3.0"
    bl_idname = "BLENDM_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP Pro"

    def draw(self, context):
        layout = self.layout
        server = getattr(bpy.types, "blendermcp_server", None)
        is_running = server is not None and server.running
        box = layout.box()
        box.label(text=f"Server Status: {'RUNNING (Port 9876)' if is_running else 'STOPPED'}", icon="PROP_ON" if is_running else "PROP_OFF")
        if not is_running:
            box.operator("blendermcp.start_server", icon="PLAY")
        else:
            box.operator("blendermcp.stop_server", icon="CANCEL")
        if server is not None and server._execute_code_allowed():
            box.label(text="execute_code: ENABLED", icon="ERROR")


class BLENDERMCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_PACKAGE

    allow_execute_code: bpy.props.BoolProperty(
        name="Allow execute_code",
        description="Allow MCP clients to execute arbitrary Python. Only enable for trusted local clients.",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "allow_execute_code")


classes = (BLENDM_OT_start_server, BLENDM_OT_stop_server, BLENDM_PT_main_panel, BLENDERMCP_AddonPreferences)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(default=False)
    # Autostart en carga en segundo plano
    if not hasattr(bpy.types, "blendermcp_server") or bpy.types.blendermcp_server is None:
        srv = BlenderMCPServer()
        srv.start()
        bpy.types.blendermcp_server = srv
        # bpy.context.scene is unavailable during startup registration (_RestrictContext)
        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            scene.blendermcp_server_running = srv.running


def unregister():
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server is not None:
        bpy.types.blendermcp_server.stop()
        bpy.types.blendermcp_server = None
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.blendermcp_server_running


if __name__ == "__main__":
    register()

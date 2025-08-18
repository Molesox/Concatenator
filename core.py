# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import pathlib
from typing import Iterable, List, Set, Tuple, Callable
import subprocess

from models import Options

ProgressCb = Callable[[int, int], None] | None


# ------------------------ Utilitaires ------------------------

def unique_paths(paths: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for p in paths:
        p = os.path.normpath(os.path.abspath(p))
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_csv_list(s: str) -> List[str]:
    if not s.strip():
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def normalize_exts(exts: List[str]) -> Set[str]:
    norm: Set[str] = set()
    for e in exts:
        e = e.lower().strip()
        if not e:
            continue
        if not e.startswith('.'):
            e = '.' + e
        norm.add(e)
    return norm


def detect_binary(path: str, sample_size: int = 8192) -> bool:
    try:
        with open(path, 'rb') as f:
            chunk = f.read(sample_size)
        if b'\x00' in chunk:
            return True
        try:
            chunk.decode('utf-8')
            return False
        except UnicodeDecodeError:
            return True
    except Exception:
        # En cas d'erreur, on suppose binaire pour éviter de polluer la sortie
        return True


def human_size(nbytes: int) -> str:
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    size = float(nbytes)
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"


# ------------------------ Scan fichiers ------------------------

def gather_candidate_files(roots: Iterable[str], opts: Options) -> List[str]:
    candidates: List[str] = []
    excluded = {d.strip() for d in opts.exclude_dirs if d.strip()}
    include_all = (len(opts.include_exts) == 0)

    for root in unique_paths(roots):
        p = pathlib.Path(root)
        if p.is_file():
            if include_all or p.suffix.lower() in opts.include_exts:
                candidates.append(str(p))
            continue

        if p.is_dir():
            it = p.rglob('*') if opts.recursive else p.glob('*')
            for sub in it:
                if sub.is_dir():
                    if sub.name in excluded:
                        pass
                    continue
                if any(part in excluded for part in sub.parts):
                    continue
                if include_all or sub.suffix.lower() in opts.include_exts:
                    candidates.append(str(sub))

    return unique_paths(candidates)


# ------------------------ Concaténation ------------------------

def _read_text_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8', errors='replace') as fin:
        return fin.read()


def _normalize_eol(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')


def clean_csharp(text: str, remove_comments: bool, remove_usings: bool) -> str:
    """Nettoie du code C# via le binaire RoslynCleaner."""
    if not (remove_comments or remove_usings):
        return text
    try:
        root = pathlib.Path(__file__).resolve().parent
        candidates = [
            root / 'RoslynCleaner' / 'RoslynCleaner.dll',
            root / 'RoslynCleaner' / 'publish' / 'RoslynCleaner.dll',
            root / 'RoslynCleaner' / 'bin' / 'Release' / 'net8.0' / 'RoslynCleaner.dll',
            root / 'RoslynCleaner' / 'bin' / 'Debug' / 'net8.0' / 'RoslynCleaner.dll',
        ]
        dll = next((p for p in candidates if p.exists()), None)
        if dll is None:
            return text
        args = ['dotnet', str(dll)]
        if remove_comments:
            args.append('--remove-comments')
        if remove_usings:
            args.append('--remove-usings')
        proc = subprocess.run(args, input=text.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            return text
        return proc.stdout.decode('utf-8')
    except Exception:
        return text


def concat_to_file(files: List[str], opts: Options, out_path: str, progress_cb: ProgressCb = None) -> Tuple[int, list[tuple[str, str]]]:
    """
    Écrit la concaténation dans out_path. Retourne (nb_fichiers_écrits, skipped[(path, raison)]).
    """
    max_bytes = int(opts.max_mb * 1024 * 1024)
    written = 0
    skipped: list[tuple[str, str]] = []

    with open(out_path, 'w', encoding='utf-8', newline='\n') as out:
        total = max(1, len(files))
        for i, fpath in enumerate(files, start=1):
            if progress_cb:
                progress_cb(i, total)

            try:
                st = os.stat(fpath)
                if st.st_size > max_bytes:
                    skipped.append((fpath, f"taille {human_size(st.st_size)} > {opts.max_mb} Mo"))
                    continue

                if opts.ignore_binaries and detect_binary(fpath):
                    skipped.append((fpath, "binaire/encodage non UTF-8"))
                    continue

                content = _read_text_file(fpath)
                if opts.normalize_eol:
                    content = _normalize_eol(content)
                if fpath.lower().endswith('.cs') and (opts.cs_remove_comments or opts.cs_remove_usings):
                    content = clean_csharp(content, opts.cs_remove_comments, opts.cs_remove_usings)

                if opts.add_headers:
                    sep = '=' * 12
                    out.write(f"\n{sep} {fpath} {sep}\n")

                out.write(content)
                if not content.endswith('\n'):
                    out.write('\n')
                written += 1
            except Exception as e:
                skipped.append((fpath, f"erreur: {e}"))
                continue

    if progress_cb:
        progress_cb(len(files), max(1, len(files)))

    return written, skipped


def concat_to_string(files: List[str], opts: Options, progress_cb: ProgressCb = None) -> Tuple[str, int, list[tuple[str, str]]]:
    """Retourne (texte_concaténé, nb_fichiers_écrits, skipped)."""
    max_bytes = int(opts.max_mb * 1024 * 1024)
    written = 0
    skipped: list[tuple[str, str]] = []
    parts: List[str] = []

    total = max(1, len(files))
    for i, fpath in enumerate(files, start=1):
        if progress_cb:
            progress_cb(i, total)
        try:
            st = os.stat(fpath)
            if st.st_size > max_bytes:
                skipped.append((fpath, f"taille {human_size(st.st_size)} > {opts.max_mb} Mo"))
                continue

            if opts.ignore_binaries and detect_binary(fpath):
                skipped.append((fpath, "binaire/encodage non UTF-8"))
                continue

            content = _read_text_file(fpath)
            if opts.normalize_eol:
                content = _normalize_eol(content)
            if fpath.lower().endswith('.cs') and (opts.cs_remove_comments or opts.cs_remove_usings):
                content = clean_csharp(content, opts.cs_remove_comments, opts.cs_remove_usings)

            if opts.add_headers:
                sep = '=' * 12
                parts.append(f"{sep} {fpath} {sep}")
            parts.append(content)
            if not content.endswith('\n'):
                parts.append('\n')
            written += 1
        except Exception as e:
            skipped.append((fpath, f"erreur: {e}"))
            continue

    if progress_cb:
        progress_cb(len(files), max(1, len(files)))

    return ''.join(parts), written, skipped
"""
CLI with user-friendly progress messages.

Changes:
- Announces start, totals, per-file "[i/N] Starting ..." messages
- Streams ffmpeg progress live (no silence) unless --dry-run
- Prints per-file duration and OK/ERR
- Final summary with report locations
"""

import argparse
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

from .config import DEFAULTS
from .converter import ConvertOptions, convert_file
from .ffmpeg_utils import (
    color,
    ffprobe_info,
    human_size,
    is_sdh_sub,
    lang_pretty,
    list_subtitle_streams,
    supports_color,
)
from .filename_infer import infer_title_and_year
from .jellyfin_naming import movie_filename, movie_folder
from .reporting import FileReport, Reporter


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Video converter (FFmpeg backend) — Talkative UX")

    p.add_argument(
        "--input",
        "-i",
        type=Path,
        default=DEFAULTS.default_input_dir,
        help=f"Input file or directory (default: {DEFAULTS.default_input_dir})",
    )
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULTS.default_output_dir,
        help=f"Output directory (default: {DEFAULTS.default_output_dir})",
    )

    p.add_argument("--container", choices=["mp4", "mkv"], help="Output container (default: mp4)")
    p.add_argument("--hevc", action="store_true", help="Use H.265 (libx265) instead of H.264")
    p.add_argument("--crf", type=int, help="CRF value (lower = better quality)")
    p.add_argument("--bitrate", type=str, help="Target video bitrate (e.g. 3000k). Overrides CRF")
    p.add_argument("--max-height", type=int, help="Limit height (e.g., 1080 for 1080p)")
    p.add_argument("--title", type=str, help="Title for metadata and filename")
    p.add_argument("--year", type=int, help="Year for metadata and filename")
    p.add_argument("--interactive", "-t", action="store_true", help="Ask for title/year if missing")
    p.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    p.add_argument(
        "--dry-run", action="store_true", default=False, help="Only print ffmpeg command"
    )
    p.add_argument("--overwrite", action="store_true", help="Allow overwriting outputs")
    p.add_argument(
        "--skip-existing", action="store_true", help="Skip when expected output already exists"
    )
    p.add_argument(
        "--no-ask-audio",
        action="store_true",
        help="Do not ask which audio track to use (default asks on TTY when multiple)",
    )
    p.add_argument(
        "--audio-track",
        type=int,
        metavar="IDX",
        default=None,
        help="Audio stream index to use (0-based). Ex.: 0 = first, 1 = second...",
    )

    p.add_argument(
        "--organize",
        action="store_true",
        help="Place outputs into 'Title (Year)/Title (Year).ext' folders",
    )
    p.add_argument(
        "--ask-missing",
        action="store_true",
        help="If title/year cannot be inferred, ask interactively per file",
    )
    p.add_argument(
        "--ask-audio", action="store_true", help="If multiple audio tracks, ask which one to use"
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show full ffmpeg logs (and progress bar when possible)",
    )

    # copy policies (mantemos simples)
    p.add_argument(
        "--copy-audio-when", choices=["aac", "never"], default="aac", help="Copy audio when AAC"
    )
    p.add_argument("--no-copy-subs", action="store_true", help="Disable subtitle copy/convert")

    p.add_argument(
        "--extract-subs", action="store_true", help="Detect and extract embedded subtitles to files"
    )
    p.add_argument(
        "--subs-out",
        type=Path,
        default=None,
        help="Directory to write extracted subtitles (default: alongside output video)",
    )
    p.add_argument(
        "--subs-select",
        type=str,
        default=None,
        help=(
            "Comma-separated subtitle stream indexes to extract (or 'all')."
            "If omitted, non-SDH are preselected and you can confirm/edit interactively."
        ),
    )
    p.add_argument(
        "--no-ask-subs",
        action="store_true",
        help="Do not prompt for subtitle selection; use --subs-select or default non-SDH",
    )

    return p.parse_args()


def ask_if_needed(args: argparse.Namespace) -> None:
    if not args.interactive:
        return
    if not args.title:
        args.title = input("Title: ").strip() or None
    if not args.year:
        y = input("Year (optional): ").strip()
        args.year = int(y) if y.isdigit() else None


def iter_inputs(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    exts = (".mp4", ".mkv", ".avi", ".mov")
    files: list[Path] = []
    if recursive:
        for ext in exts:
            files.extend(input_path.rglob(f"*{ext}"))
    else:
        for ext in exts:
            files.extend(input_path.glob(f"*{ext}"))
    return files


def prompt_title_year(
    suggest_title: str | None, suggest_year: int | None
) -> tuple[str, int | None]:
    print("  → Need metadata. Press Enter to accept suggestions.")
    title = input(f"    Title [{suggest_title or ''}]: ").strip() or (suggest_title or "")
    year_in = input(f"    Year  [{suggest_year or ''}]: ").strip()
    year = (
        int(year_in) if year_in.isdigit() else (suggest_year if suggest_year is not None else None)
    )
    # Small confirm/edit loop
    confirm = input(f"    Use '{title}' ({year or '—'})? [Y/n]: ").strip().lower()
    if confirm == "n":
        return prompt_title_year(title, year)
    return title, year


def _describe_audio_stream(s: dict) -> str:
    tags = s.get("tags") or {}
    lang = (tags.get("language") or "und").lower()
    title = tags.get("title") or ""
    codec = s.get("codec_name") or "?"
    ch = s.get("channels") or "?"
    extras = f" | {title}" if title else ""
    return f"lang={lang} | codec={codec} | ch={ch}{extras}"


def prompt_audio_choice(streams: list[dict]) -> int:
    print("  → Multiple audio tracks detected. Choose one (index):")
    for i, s in enumerate(streams):
        print(f"    [{i}] {_describe_audio_stream(s)}")
    default = 0
    while True:
        raw = input(f"    Use which index? [default: {default}]: ").strip()
        if raw == "":
            return default
        if raw.isdigit():
            idx = int(raw)
            if 0 <= idx < len(streams):
                return idx
        print(f"    Invalid choice. Enter a number between 0 and {len(streams)-1}.")


def _truncate(s: str, maxlen: int = 40) -> str:
    s = s or ""
    return (s[: maxlen - 1] + "…") if len(s) > maxlen else s


def _parse_indexes(inp: str, max_idx: int) -> list[int]:
    """
    Aceita: vírgula, espaço ou ';' como separadores; intervalos 2-5; 'all'/'none'.
    Ignora fora de faixa; deduplica.
    """
    s = (inp or "").strip().lower()
    if not s:
        return []
    if s in {"all", "none"}:
        return list(range(max_idx + 1)) if s == "all" else []
    picks: set[int] = set()
    for part in re.split(r"[,\s;]+", s):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                start, end = int(a), int(b)
                if start > end:
                    start, end = end, start
                for v in range(start, end + 1):
                    if 0 <= v <= max_idx:
                        picks.add(v)
        elif part.isdigit():
            v = int(part)
            if 0 <= v <= max_idx:
                picks.add(v)
    return sorted(picks)


def prompt_subs_choice(streams: list[dict], preselect: list[int]) -> list[int]:
    """Tabela alinhada e confirmação final. Enter aceita sugestão (não-SDH)."""
    use_color = supports_color()
    use_flags = False  # emojis desativados => alinhamento perfeito
    print("  → Subtitles detected. Choose which to extract.")
    hdr = f"{'IDX':>3}  {'LANG':<28} {'CODEC':<8} {'CH':<2} {'FORCED':<6} {'SDH':<3}  TITLE"
    print(color(hdr, "1;36") if use_color else hdr)

    for i, s in enumerate(streams):
        tags = s.get("tags") or {}
        lang = (tags.get("language") or "und").lower()
        title = _truncate(tags.get("title") or "", 40)
        codec = (s.get("codec_name") or "?").lower()
        ch = s.get("channels") or ""
        forced = "yes" if int((s.get("disposition") or {}).get("forced", 0)) == 1 else "no"
        sdh = "yes" if is_sdh_sub(s) else "no"
        lang_col = f"{lang_pretty(lang, flags=use_flags)} ({lang.upper()})"
        mark = "*" if i in preselect else " "
        line = (
            f"{mark}{i:>2}   {lang_col:<28} {codec:<8} {str(ch):<2} "
            f"{forced:<6} {sdh:<3}  {title}"
        )
        print(color(line, "1;33") if (use_color and i in preselect) else line)

    default_str = ",".join(str(i) for i in preselect) if preselect else "none"
    while True:
        raw = input(f"    Select (e.g. 0,2-4 or 'all'/'none') [default: {default_str}]: ").strip()
        picks = preselect if raw == "" else _parse_indexes(raw, len(streams) - 1)
        if picks == [] and raw.lower() not in {"", "none"}:
            print(f"    No valid indexes parsed. Try numbers/ranges within 0..{len(streams)-1}.")
            continue
        print(f"    → Using: {picks if picks else 'none'}")
        ok = input("    Confirm? [Y/n]: ").strip().lower()
        if ok in {"", "y", "yes"}:
            return picks


def run_cli() -> int:
    args = parse_args()
    ask_if_needed(args)
    interactive_tty = sys.stdin.isatty()

    if not args.input.exists():
        print(f"⚠️  Input path not found: {args.input}")
        print("   Dica: ajuste em .env (JFCVT_INPUT_DIR) ou passe --input.")
        return 1
    inputs = iter_inputs(args.input, bool(args.recursive))

    if not inputs:
        print("⚠️ No input files found.")
        return 0

    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build opts
    opts = ConvertOptions(
        hevc=bool(args.hevc),
        crf=args.crf,
        bitrate=args.bitrate,
        max_height=args.max_height,
        container=args.container,
        title=args.title,
        year=args.year,
        dry_run=bool(args.dry_run),
        verbose=bool(args.verbose),
        audio_track=getattr(args, "audio_track", None),
        no_copy_subs=bool(args.no_copy_subs),
    )

    # Skip-existing (baseado no nome final esperado)
    if args.skip_existing and not opts.dry_run and args.title:
        cont = (args.container or DEFAULTS.container)
        year_part = f" ({args.year})" if args.year else ""
        base_name = f"{args.title}{year_part}.{cont}"
        expected = out_dir / base_name
        before = len(inputs)
        if expected.exists():
            inputs = []
        skipped = before - len(inputs)
        if skipped:
            print(f"⏭️ Skipping {skipped} file(s): output already exists -> {expected.name}")
            if not inputs:
                print("Nothing to do.")
                return 0

    # Header
    print("🎬 Starting conversion")
    print(f"• Input:     {args.input}")
    print(f"• Output:    {out_dir}")
    print(f"• Files:     {len(inputs)}")
    print(f"• Mode:      {'DRY-RUN' if opts.dry_run else 'EXECUTE'}")
    if opts.max_height:
        print(f"• Max height: {opts.max_height}")
    if opts.hevc:
        print("• Codec:     H.265 (libx265)")
    else:
        print("• Codec:     H.264 (libx264)")
    print("-" * 60)

    if inputs:
        print(f"🔧 Preparing {len(inputs)} file(s) for conversion...\n")

    reporter = Reporter(DEFAULTS.report_csv, DEFAULTS.report_json)

    ok_count = 0
    err_count = 0
    skipped_count = 0
    start_all = time.time()

    total = len(inputs)
    for idx, src in enumerate(inputs, start=1):
        input_size = src.stat().st_size if src.exists() else 0

        # 1) Per-file: prefer CLI args; else infer from filename
        if args.title:
            file_title = args.title
            file_year = args.year
        else:
            inferred_title, inferred_year = infer_title_and_year(src.name)
            file_title = inferred_title
            file_year = args.year if args.year else inferred_year

        # 2) Se necessário, decidir/perguntar a faixa de áudio
        chosen_audio_track = args.audio_track
        if chosen_audio_track is None:
            try:
                info = ffprobe_info(src)
                audio_streams = [
                    s for s in info.get("streams", []) if s.get("codec_type") == "audio"
                ]
                if len(audio_streams) == 1:
                    chosen_audio_track = 0
                    if args.verbose:
                        desc0 = _describe_audio_stream(audio_streams[0])
                        print(f"  ℹ️  Single audio track detected → using index 0 ({desc0})")
                elif len(audio_streams) >= 2:
                    # Regra: pergunta se estivermos num TTY
                    # e se o usuário não bloqueou com --no-ask-audio.
                    if interactive_tty and not args.no_ask_audio:
                        chosen_audio_track = prompt_audio_choice(audio_streams)
                    else:
                        # Não interativo: cai no índice 0 de forma determinística
                        chosen_audio_track = 0
                    if args.verbose and chosen_audio_track is not None:
                        chdesc = _describe_audio_stream(audio_streams[chosen_audio_track])
                        print(f"  ℹ️  Chosen audio index: {chosen_audio_track} ({chdesc})")
                else:
                    # padrão: usa 0 se não pedir escolha
                    chosen_audio_track = 0 if audio_streams else 0
            except Exception as e:
                # se ffprobe falhar aqui, converter cuidará do fallback
                if args.verbose:
                    msg = (
                        f"  ⚠️  ffprobe failed during audio inspection: {e} — "
                        "falling back to index 0"
                    )
                    print(msg)
                chosen_audio_track = 0

        # 3) Decide output dir (organize or flat)
        target_dir = out_dir
        if args.organize:
            target_dir = out_dir / movie_folder(file_title, file_year)
            target_dir.mkdir(parents=True, exist_ok=True)

        # 3) Skip-existing (ONLY compute expected_out here; don't use it elsewhere)
        if args.skip_existing and not opts.dry_run:
            expected_out = target_dir / movie_filename(
                file_title, file_year, (args.container or DEFAULTS.container)
            )
            if expected_out.exists():
                skipped_count += 1
                rel = expected_out.relative_to(out_dir)
                print(f"[{idx}/{total}] ⏭️  Skipping: {src.name} → {rel} (já existe)")
                reporter.add(
                    FileReport(
                        input_path=str(src),
                        output_path=str(expected_out),
                        status="skipped",
                        error="already exists",
                        duration_sec=0.0,
                        input_size=input_size,
                        output_size=expected_out.stat().st_size if expected_out.exists() else 0,
                    )
                )
                print("-" * 60)
                continue

        # 4) Mensagem de início (uma vez só)
        print(
            f"[{idx}/{total}] Iniciando: {src.name} → '{file_title}' ({file_year or '-'})  "
            f"({human_size(input_size)})"
        )

        t0 = time.time()

        # 5) Clone opts com título/ano por arquivo
        file_opts = replace(opts, title=file_title, year=file_year, audio_track=chosen_audio_track)

        # 6) (opcional) Extração de legendas embutidas
        if args.extract_subs:
            try:
                info = ffprobe_info(src)
                sub_streams = list_subtitle_streams(info)
                if sub_streams:
                    # sugestão: apenas não-SDH
                    non_sdh = [i for i, s in enumerate(sub_streams) if not is_sdh_sub(s)]
                    suggested = non_sdh if non_sdh else []
                    # seleção automática se --subs-select foi fornecido
                    if args.subs_select:
                        if args.subs_select.strip().lower() == "all":
                            picks = list(range(len(sub_streams)))
                        else:
                            picks = [int(x) for x in args.subs_select.split(",") if x.strip() != ""]
                    else:
                        if not args.no_ask_subs and sys.stdin.isatty():
                            picks = prompt_subs_choice(sub_streams, suggested)
                        else:
                            picks = suggested  # não-interativo: tarefa limpa
                    # decide pasta: por padrão AO LADO do vídeo de saída (melhor para players)
                    subs_dir = args.subs_out or target_dir
                    base_name = movie_filename(
                        file_title, file_year, (args.container or DEFAULTS.container)
                    )
                    base_name = Path(base_name).with_suffix("").name  # sem extensão
                    # chama extração
                    from .converter import extract_subs  # import leve, evita ciclo

                    generated = extract_subs(src, sub_streams, picks, subs_dir, base_name)
                    if args.verbose:
                        if generated:
                            print("  💬 Subtitles extracted:")
                            for p in generated:
                                print("     •", p)
                        else:
                            print("  ℹ️  No subtitles extracted.")
                else:
                    if args.verbose:
                        print("  ℹ️  No embedded subtitles found.")
            except Exception as e:
                print(f"  ⚠️  Subtitle inspection/extraction failed: {e}")

        # 7) Converter (salva em target_dir)
        success, err, outpath, cmd = convert_file(src, target_dir, file_opts)

        print(" ffmpeg:", " ".join(cmd))

        duration = time.time() - t0
        if success:
            ok_count += 1
            out_size = 0
            try:
                if not opts.dry_run and outpath.exists():
                    out_size = outpath.stat().st_size
            except Exception:
                out_size = 0
            rel_out = outpath.relative_to(out_dir)
            print(f" ✅ Concluído em {duration:.1f}s  →  {rel_out}  ({human_size(out_size)})")
            status = "dry-run" if opts.dry_run else "success"
            reporter.add(
                FileReport(
                    input_path=str(src),
                    output_path=str(outpath),
                    status=status,
                    error="",
                    duration_sec=duration,
                    input_size=input_size,
                    output_size=out_size,
                )
            )
        else:
            err_count += 1
            print(f" ❌ Falhou em {duration:.1f}s  →  {src.name}")
            if err:
                print(f"    Motivo: {err}")
            reporter.add(
                FileReport(
                    input_path=str(src),
                    output_path=str(outpath),
                    status="fail",
                    error=err,
                    duration_sec=duration,
                    input_size=input_size,
                    output_size=0,
                )
            )

        print("-" * 60)

    reporter.write()
    elapsed = time.time() - start_all
    print("🏁 Finalizado")
    skipped_str = f"  • Pulados: {skipped_count}" if skipped_count else ""
    print(f"• Sucesso: {ok_count}  • Falhas: {err_count}{skipped_str}")
    print(f"• Tempo total: {elapsed:.1f}s")
    print(f"• Relatórios: {DEFAULTS.report_csv}  |  {DEFAULTS.report_json}")
    return 0

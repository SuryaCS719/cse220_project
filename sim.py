#!/usr/bin/env python3
import argparse
import csv
import json
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


# Simple MESI states for a single shared cache model
INVALID, SHARED, EXCLUSIVE, MODIFIED = "I", "S", "E", "M"


@dataclass
class CacheLine:
    tag: int = -1
    state: str = INVALID
    owner: Optional[int] = None  # core id for E/M
    sharers: set = field(default_factory=set)
    last_writer_core: int = -1
    last_word: int = 0
    fs_conf: int = 0
    fs_suspect: bool = False


@dataclass
class Config:
    line_bytes: int = 64
    sets: int = 64
    assoc: int = 8
    word_bytes: int = 4
    fs_threshold: int = 2
    false_sharing_fix: bool = False
    hit_latency: int = 4
    miss_latency: int = 40
    inv_latency: int = 10


class Cache:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.lines: List[List[CacheLine]] = [
            [CacheLine() for _ in range(cfg.assoc)] for _ in range(cfg.sets)
        ]
        self.repl_idx = [0 for _ in range(cfg.sets)]

    def _index_tag(self, addr: int) -> Tuple[int, int]:
        line_addr = addr // self.cfg.line_bytes
        return line_addr % self.cfg.sets, line_addr

    def _word_idx(self, addr: int) -> int:
        return (addr // self.cfg.word_bytes) % (self.cfg.line_bytes // self.cfg.word_bytes)

    def probe(self, addr: int) -> Tuple[CacheLine, bool]:
        idx, tag = self._index_tag(addr)
        for line in self.lines[idx]:
            if line.tag == tag and line.state != INVALID:
                return line, True
        repl = self.lines[idx][self.repl_idx[idx]]
        self.repl_idx[idx] = (self.repl_idx[idx] + 1) % self.cfg.assoc
        repl.tag, repl.state, repl.owner, repl.sharers = tag, INVALID, None, set()
        return repl, False

    def access(self, core: int, is_write: bool, addr: int, stats, logger):
        cfg = self.cfg
        word_idx = self._word_idx(addr)
        line, hit = self.probe(addr)

        # Coherence + detector logic
        if hit:
            if is_write:
                # If another core has it, invalidate them unless fix-up suppresses
                if line.state in (SHARED, EXCLUSIVE, MODIFIED) and line.owner != core:
                    self._maybe_detect(line, core, word_idx, stats, logger)
                    if not (line.fs_suspect and cfg.false_sharing_fix and line.last_word != word_idx):
                        stats["invalidations"] += len(line.sharers - {core})
                        stats["stall_cycles"] += cfg.inv_latency
                        line.sharers = {core}
                    else:
                        stats["avoided_invalidations"] += len(line.sharers - {core})
                    line.owner = core
                    line.state = MODIFIED
                else:
                    line.owner = core
                    line.state = MODIFIED
            else:
                # read hit
                if line.state == MODIFIED and line.owner != core:
                    self._maybe_detect(line, core, word_idx, stats, logger)
                    if not (line.fs_suspect and cfg.false_sharing_fix and line.last_word != word_idx):
                        stats["invalidations"] += 1
                        stats["stall_cycles"] += cfg.inv_latency
                        line.sharers = {core, line.owner}
                        line.state = SHARED
                    else:
                        stats["avoided_invalidations"] += 1
                        line.sharers.add(core)
                        line.state = SHARED
                else:
                    line.sharers.add(core)
                    if line.state == EXCLUSIVE:
                        line.state = SHARED
            stats["hits"] += 1
        else:
            # Miss: bring line in, apply detector on coherence event if others own
            self._maybe_detect(line, core, word_idx, stats, logger)
            if is_write:
                if line.state != INVALID and line.owner is not None and line.owner != core:
                    if not (line.fs_suspect and cfg.false_sharing_fix and line.last_word != word_idx):
                        stats["invalidations"] += 1
                        stats["stall_cycles"] += cfg.inv_latency
                    else:
                        stats["avoided_invalidations"] += 1
                line.owner = core
                line.state = MODIFIED
                line.sharers = {core}
            else:
                if line.state != INVALID and line.owner is not None and line.owner != core:
                    if not (line.fs_suspect and cfg.false_sharing_fix and line.last_word != word_idx):
                        stats["invalidations"] += 1
                        stats["stall_cycles"] += cfg.inv_latency
                    else:
                        stats["avoided_invalidations"] += 1
                line.owner = core
                line.state = EXCLUSIVE
                line.sharers = {core}
            line.tag = self._index_tag(addr)[1]
            stats["misses"] += 1
            stats["stall_cycles"] += cfg.miss_latency

        # Update detector metadata on write or ownership change
        if is_write or line.owner == core:
            line.last_writer_core = core
            line.last_word = word_idx

    def _maybe_detect(self, line: CacheLine, core: int, word_idx: int, stats, logger):
        cfg = self.cfg
        if line.state == INVALID:
            return
        if line.last_writer_core != -1 and line.last_writer_core != core and line.last_word != word_idx:
            line.fs_conf = min(line.fs_conf + 1, 3)
            if line.fs_conf >= cfg.fs_threshold and not line.fs_suspect:
                line.fs_suspect = True
                stats["suspect_lines"] += 1
            logger.log_suspect(core, line, word_idx)
            stats["suspect_events"] += 1
        else:
            line.fs_conf = max(line.fs_conf - 1, 0)


class Logger:
    def __init__(self, path: Optional[str]):
        self.path = path
        self.file = open(path, "w", newline="") if path else None
        self.writer = csv.writer(self.file) if self.file else None
        if self.writer:
            self.writer.writerow(["event_id", "addr", "core", "word_idx", "prev_core", "prev_word", "fs_conf", "fs_suspect"])
        self.event_id = 0

    def log_suspect(self, core: int, line: CacheLine, word_idx: int):
        if not self.writer:
            return
        self.event_id += 1
        self.writer.writerow(
            [
                self.event_id,
                line.tag,
                core,
                word_idx,
                line.last_writer_core,
                line.last_word,
                line.fs_conf,
                int(line.fs_suspect),
            ]
        )

    def close(self):
        if self.file:
            self.file.close()


def run_trace(trace_path: str, cfg: Config, log_path: Optional[str]) -> Dict[str, int]:
    cache = Cache(cfg)
    stats = defaultdict(int)
    stats["instructions"] = 0
    logger = Logger(log_path)
    with open(trace_path) as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.strip().split()
            core = int(parts[0])
            op = parts[1].upper()
            addr = int(parts[2], 0)
            is_write = op.startswith("W")
            cache.access(core, is_write, addr, stats, logger)
            stats["instructions"] += 1
            stats["stall_cycles"] += cfg.hit_latency
    logger.close()
    # Derived stats
    inv = stats["invalidations"]
    instr = max(stats["instructions"], 1)
    stats["ipki"] = inv * 1000.0 / instr
    total_cycles = stats["stall_cycles"]
    stats["ipc_proxy"] = instr / total_cycles if total_cycles else 0.0
    return stats


def main():
    ap = argparse.ArgumentParser(description="False-sharing aware coherence simulator (trace-driven)")
    ap.add_argument("trace", help="Trace file: lines of 'core R/W addr'")
    ap.add_argument("--false-sharing-fix", action="store_true", help="Enable fix-up suppression for suspect lines")
    ap.add_argument("--fs-threshold", type=int, default=2, help="Confidence threshold to mark suspect")
    ap.add_argument("--word-bytes", type=int, default=4, help="Word granularity in bytes")
    ap.add_argument("--log", type=str, default=None, help="Path to suspect CSV log")
    ap.add_argument("--json", type=str, default=None, help="Path to write summary stats JSON")
    args = ap.parse_args()

    cfg = Config(
        word_bytes=args.word_bytes,
        fs_threshold=args.fs_threshold,
        false_sharing_fix=args.false_sharing_fix,
    )
    stats = run_trace(args.trace, cfg, args.log)
    print(json.dumps(stats, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(stats, f, indent=2)


if __name__ == "__main__":
    main()

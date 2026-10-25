# -*- coding: utf-8 -*-
"""播放队列（纯逻辑，无 Qt 依赖）：负责播放模式下的索引推进。

模式语义：
- sequential 顺序播放：播完最后一首停止；手动下一首到末尾即停
- loop       列表循环：末尾自动回到第一首
- single     单曲循环：自动播放结束时重播当前曲；手动切歌正常前进
- shuffle    随机播放：维护一个随机播放顺序，播完一轮重新洗牌
"""
from __future__ import annotations

import random

from app.models import MODE_LOOP, MODE_SINGLE, MODE_SHUFFLE


class PlayQueue:
    def __init__(self, ids: list[str] | None = None, index: int = 0, mode: str = MODE_LOOP):
        self._ids: list[str] = list(ids or [])
        self._order: list[str] = list(self._ids)
        self._pos: int = index if self._ids else -1
        self._mode: str = mode
        if mode == MODE_SHUFFLE:
            self._reshuffle_keeping_current()

    # ---------- 内部 ----------

    def _shuffled_from(self, start_pos: int) -> list[str]:
        """以 start_pos 为首，其余随机排列；start_pos 越界时整体随机。"""
        if 0 <= start_pos < len(self._ids):
            rest = self._ids[:start_pos] + self._ids[start_pos + 1:]
            random.shuffle(rest)
            return [self._ids[start_pos], *rest]
        rest = list(self._ids)
        random.shuffle(rest)
        return rest

    def _reshuffle_keeping_current(self) -> None:
        """重排播放顺序，保持当前曲在首位（指针归零）。"""
        cur = self.current
        if cur is not None and cur in self._ids:
            self._order = self._shuffled_from(self._ids.index(cur))
        else:
            self._order = self._shuffled_from(-1)
        self._pos = 0

    def _advance(self, auto: bool) -> str | None:
        """推进到下一首，返回曲目 id；None 表示停止。"""
        if not self._order or self._pos < 0:
            return None
        if auto and self._mode == MODE_SINGLE:
            return self.current  # 单曲循环：重播当前
        nxt = self._pos + 1
        if nxt >= len(self._order):
            if self._mode == MODE_LOOP:
                self._pos = 0
                return self.current
            if self._mode == MODE_SHUFFLE:
                self._order = self._shuffled_from(-1)
                self._pos = 0
                return self.current
            return None  # sequential 播完停止
        self._pos = nxt
        return self.current

    # ---------- 查询 ----------

    @property
    def current(self) -> str | None:
        if 0 <= self._pos < len(self._order):
            return self._order[self._pos]
        return None

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def ids(self) -> list[str]:
        return list(self._order)

    def __len__(self) -> int:
        return len(self._order)

    # ---------- 操作 ----------

    def set_ids(self, ids: list[str], index: int = 0) -> None:
        """重建队列（如切换了视图/歌单）。"""
        self._ids = list(ids)
        self._pos = index if self._ids else -1
        if self._mode == MODE_SHUFFLE:
            self._order = self._shuffled_from(self._pos)
        else:
            self._order = list(self._ids)

    def jump_to(self, tid: str) -> bool:
        """用户指定播放某曲（双击列表）。"""
        if tid not in self._ids:
            return False
        index = self._ids.index(tid)
        if self._mode == MODE_SHUFFLE:
            self._order = self._shuffled_from(index)
            self._pos = 0
        else:
            self._pos = index
        return True

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == MODE_SHUFFLE:
            self._reshuffle_keeping_current()

    def next(self, auto: bool = False) -> str | None:
        return self._advance(auto)

    def previous(self) -> str | None:
        if not self._order or self._pos < 0:
            return None
        if self._pos > 0:
            self._pos -= 1
            return self.current
        if self._mode in (MODE_LOOP, MODE_SHUFFLE):
            self._pos = len(self._order) - 1
            return self.current
        return self.current  # sequential 停在首曲

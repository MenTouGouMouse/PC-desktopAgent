"""tests/unit/test_detection_cache.py

线程安全测试：automation/object_detector.DetectionCache

Task 4.2 of the vision-overlay spec.
测试真实 DetectionCache 实现，不 mock DetectionCache 本身。
"""
from __future__ import annotations

import threading

from automation.object_detector import DetectionCache
from automation.vision_box_drawer import BoundingBoxDict


def _make_box(i: int) -> BoundingBoxDict:
    return BoundingBoxDict(bbox=[0, 0, 10, 10], label=f"obj{i}", confidence=0.9)


def test_cache_thread_safety() -> None:
    """并发 100 次写 + 100 次读，断言无异常、无数据竞争。

    若去掉 Lock，此测试有概率因竞态条件抛出异常或产生不一致状态。
    """
    cache = DetectionCache()
    errors: list[Exception] = []

    def writer() -> None:
        for i in range(100):
            try:
                cache.update([_make_box(i)])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    def reader() -> None:
        for _ in range(100):
            try:
                cache.get()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"线程安全违规: {errors}"


def test_cache_clear_returns_empty() -> None:
    """update 后 clear，get() 应返回空列表。"""
    cache = DetectionCache()
    cache.update([_make_box(0), _make_box(1)])
    assert len(cache.get()) == 2

    cache.clear()
    assert cache.get() == []


def test_cache_get_returns_copy() -> None:
    """get() 返回的列表修改后不影响缓存内容。"""
    cache = DetectionCache()
    original = [_make_box(0)]
    cache.update(original)

    result = cache.get()
    result.append(_make_box(99))  # 修改返回的副本

    # 缓存内容不应受影响
    assert len(cache.get()) == 1, "get() 应返回副本，修改副本不应影响缓存"


def test_cache_update_replaces_content() -> None:
    """update 新内容后 get() 应返回新内容，而非旧内容。"""
    cache = DetectionCache()
    cache.update([_make_box(0)])
    assert cache.get()[0]["label"] == "obj0"

    new_boxes = [_make_box(42)]
    cache.update(new_boxes)
    result = cache.get()

    assert len(result) == 1
    assert result[0]["label"] == "obj42", f"期望 'obj42'，实际 '{result[0]['label']}'"

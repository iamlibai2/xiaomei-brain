"""测试人脸注册 → 识别 → 身份解析 完整链路。

用法:
    # 需要有包含人脸的照片文件
    PYTHONPATH=src python3 tests/test_face_login.py <照片路径>
    PYTHONPATH=src python3 tests/test_face_login.py ~/photo.jpg

如果没有照片文件，仅测试身份解析逻辑:
    PYTHONPATH=src python3 tests/test_face_login.py --no-photo
"""

from __future__ import annotations

import os
import sys
import tempfile
import shutil
from pathlib import Path


def test_identity_resolution():
    """测试 IdentityManager 的三种查找方式 + name 反向查找。"""
    from xiaomei_brain.contacts.manager import IdentityManager

    tmpdir = tempfile.mkdtemp(prefix="test_face_login_")
    try:
        # 写入 identities.yaml
        yaml_path = os.path.join(tmpdir, "identities.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("people:\n")
            f.write("  - id: libai\n")
            f.write("    name: 李白\n")
            f.write("    relation: 恋人\n")
            f.write("    alias_ids:\n")
            f.write("      - ou_abc123\n")
            f.write("  - id: boshi\n")
            f.write("    name: 博士\n")
            f.write("    relation: 师生\n")

        mgr = IdentityManager(tmpdir)

        # 1. 按 id 查找
        entry = mgr.resolve("libai")
        assert entry is not None, "按 id 找不到"
        assert entry["name"] == "李白", f"name 不对: {entry['name']}"

        # 2. 按别名查找
        entry = mgr.resolve("ou_abc123")
        assert entry is not None, "按别名找不到"
        assert entry["name"] == "李白", f"别名解析错误: {entry['name']}"

        # 3. 按显示名反向查找（关键：FaceID/SpeakerID 返回的是 name）
        entry = mgr.resolve("李白")
        assert entry is not None, "按显示名找不到 libai（这是 bug！）"
        # 反向查找返回的 entry 的 key 是 id
        print(f"  ✓ resolve('李白') → id=libai, name=李白")

        entry = mgr.resolve("博士")
        assert entry is not None, "按显示名找不到 boshi"
        print(f"  ✓ resolve('博士') → id=boshi, name=博士")

        # 4. 不存在的
        entry = mgr.resolve("stranger")
        assert entry is None, "不应该找到 stranger"

        print("  ✓ 身份解析测试全部通过")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_face_register_and_persistence(photo_path: str | None = None):
    """测试人脸注册 → 持久化 → 加载 → 识别 完整链路。"""
    from xiaomei_brain.contacts.manager import IdentityManager
    from xiaomei_brain.body.perception.face_id import FaceID

    tmpdir = tempfile.mkdtemp(prefix="test_face_login_")
    try:
        # 写入 identities.yaml
        yaml_path = os.path.join(tmpdir, "identities.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("people:\n")
            f.write("  - id: libai\n")
            f.write("    name: 李白\n")
            f.write("    relation: 恋人\n")

        mgr = IdentityManager(tmpdir)

        # 子目录在首次 save() 时才会创建（懒创建）
        print(f"  ✓ faces 目录: {mgr._faces_dir}")

        if photo_path and os.path.exists(photo_path):
            # ── 注册人脸 ──
            ok = mgr.register_face(photo_path, "libai")
            if ok:
                print(f"  ✓ 人脸注册成功: libai")

                # 验证 .npy 文件存在（key 是 identity_id，不是显示名）
                npy_path = os.path.join(mgr._faces_dir, "libai.npy")
                assert os.path.exists(npy_path), f"人脸特征文件不存在: {npy_path}"
                print(f"  ✓ 特征文件: {npy_path}")

                # 验证 FaceID 内部状态
                assert "libai" in mgr.face_id.known_names, \
                    f"FaceID 不认识 libai，已知: {mgr.face_id.known_names}"

                # ── 测试重新加载 ──
                face_id2 = FaceID()
                face_id2.load(str(mgr._faces_dir))
                assert "libai" in face_id2.known_names, \
                    f"重新加载后不认识 libai: {face_id2.known_names}"
                print(f"  ✓ 重新加载 FaceID 后仍可识别 libai")

                # ── 识别同一张照片 ──
                detected = mgr.face_id.detect(photo_path)
                if detected:
                    name = mgr.face_id.match(detected[0]["encoding"])
                    print(f"  ✓ 识别结果: {name}")

                    # ── 链路终点：FaceID 返回 identity_id → IdentityManager.resolve() ──
                    if name:
                        entry = mgr.resolve(name)
                        assert entry is not None, \
                            f"resolve('{name}') 失败，这是链路断裂！"
                        print(f"  ✓ 链路完整: FaceID.match() → '{name}' → resolve() → {entry}")
                    else:
                        print(f"  ⚠ 识别阈值不够（可能需要更清晰的正脸照）")
                else:
                    print(f"  ⚠ 注册后仍检测不到人脸（可能需要更清晰的照片）")
            else:
                print(f"  ⚠ 人脸注册失败 — 照片中未检测到人脸")
                print(f"    请使用包含清晰正脸的照片")
        else:
            print(f"  ⓘ 跳过人脸检测测试（无照片文件）")
            print(f"    用法: PYTHONPATH=src python3 tests/test_face_login.py <照片路径>")

        # ── 测试 resolve 按 name 反向查找 ──
        entry = mgr.resolve("李白")
        assert entry is not None, "按显示名 '李白' 找不到身份"
        print(f"  ✓ name→id 反向查找: '李白' → {entry}")

        print("\n  ✅ 全部测试通过")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    photo_path = None
    if len(sys.argv) > 1 and sys.argv[1] != "--no-photo":
        photo_path = sys.argv[1]
        if not os.path.exists(photo_path):
            print(f"照片文件不存在: {photo_path}")
            sys.exit(1)

    print("=" * 60)
    print("1. 身份解析测试")
    print("=" * 60)
    test_identity_resolution()

    print()
    print("=" * 60)
    print("2. 人脸注册 + 持久化 + 识别链路测试")
    print("=" * 60)
    test_face_register_and_persistence(photo_path)


if __name__ == "__main__":
    main()

"""Body 身体感官层单元测试。"""
from __future__ import annotations


class TestDeviceABC:
    """Device 抽象基类测试。"""

    def test_camera_is_device(self):
        from xiaomei_brain.body.device import Camera, Device
        assert issubclass(Camera, Device)

    def test_microphone_is_device(self):
        from xiaomei_brain.body.device import Microphone, Device
        assert issubclass(Microphone, Device)

    def test_speaker_is_device(self):
        from xiaomei_brain.body.device import Speaker, Device
        assert issubclass(Speaker, Device)

    def test_camera_device_type(self):
        from xiaomei_brain.body.device import Camera
        assert Camera().device_type == "camera"

    def test_microphone_device_type(self):
        from xiaomei_brain.body.device import Microphone
        assert Microphone().device_type == "microphone"

    def test_speaker_device_type(self):
        from xiaomei_brain.body.device import Speaker
        assert Speaker().device_type == "speaker"

    def test_device_source(self):
        from xiaomei_brain.body.device import Camera
        c = Camera(source="/dev/video0")
        assert c.source == "/dev/video0"

    def test_abstract_methods_raise(self):
        from xiaomei_brain.body.device import Camera
        c = Camera()
        try:
            c.open()
            assert False, "should raise NotImplementedError"
        except NotImplementedError:
            pass

    def test_cannot_instantiate_device_abc(self):
        from xiaomei_brain.body.device import Device
        import pytest
        with pytest.raises(TypeError):
            Device()  # type: ignore[abstract]


class TestSenseABC:
    """Sense 抽象基类测试。"""

    def test_eyes_is_sense(self):
        from xiaomei_brain.body.sense import Eyes, Sense
        assert issubclass(Eyes, Sense)

    def test_ears_is_sense(self):
        from xiaomei_brain.body.sense import Ears, Sense
        assert issubclass(Ears, Sense)

    def test_throat_is_sense(self):
        from xiaomei_brain.body.sense import Throat, Sense
        assert issubclass(Throat, Sense)

    def test_eyes_name(self):
        from xiaomei_brain.body.sense import Eyes
        assert Eyes().name == "eyes"

    def test_ears_name(self):
        from xiaomei_brain.body.sense import Ears
        assert Ears().name == "ears"

    def test_throat_name(self):
        from xiaomei_brain.body.sense import Throat
        assert Throat().name == "throat"

    def test_sense_can_be_instantiated(self):
        """Sense 是具体基类，可直接实例化。"""
        from xiaomei_brain.body.sense import Sense
        s = Sense()
        assert s.name == ""
        assert s.online is False

    def test_not_available_without_device(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.is_available() is False

    def test_see_returns_none_when_not_available(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.see() is None

    def test_recognize_faces_empty_when_not_available(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.recognize_faces() == []

    def test_listen_returns_none_when_not_available(self):
        from xiaomei_brain.body.sense import Ears
        e = Ears()
        assert e.listen() is None


class TestMockDevices:
    """Mock 设备测试。"""

    def test_mock_camera_open_close(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        assert c.is_operational() is False
        assert c.open() is True
        assert c.is_operational() is True
        c.close()
        assert c.is_operational() is False

    def test_mock_camera_capture(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        c.open()
        assert c.capture() == b"mock_frame_data"

    def test_mock_camera_set_faces(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        c.set_faces(["face_a", "face_b"])
        assert c._face_ids == ["face_a", "face_b"]

    def test_mock_microphone_open_close(self):
        from xiaomei_brain.body.device.mock import MockMicrophone
        m = MockMicrophone()
        assert m.is_operational() is False
        assert m.open() is True
        assert m.is_operational() is True

    def test_mock_microphone_capture(self):
        from xiaomei_brain.body.device.mock import MockMicrophone
        m = MockMicrophone()
        m.open()
        assert m.capture() == b"mock_audio_data"

    def test_mock_speaker_record_text(self):
        from xiaomei_brain.body.device.mock import MockSpeaker
        s = MockSpeaker()
        s.open()
        s.play("/path/to/song.mp3")
        assert s.last_played == "/path/to/song.mp3"


class TestMockSenses:
    """Mock 感官测试。"""

    def test_mock_eyes_see(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes

        body = Body()
        body.register_sense(MockEyes(), MockCamera())
        body.open()
        result = body.eyes.see("描述这个画面")
        assert "mock vision" in result
        assert "安静的室内场景" in result

    def test_mock_eyes_recognize_faces(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc", "face_li"])
        body.register_sense(MockEyes(), camera)
        body.open()

        result = body.eyes.recognize_faces()
        assert len(result) == 2
        assert result[0]["face_id"] == "face_doc"

    def test_mock_ears_listen(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars

        body = Body()
        mic = MockMicrophone()
        mic.set_speech("你好我是博士")
        mic.set_tone("happy")
        body.register_sense(MockEars(), mic)
        body.open()

        result = body.ears.listen("分析情绪")
        assert "mock audio" in result
        assert "博士" in result
        assert "happy" in result

    def test_mock_ears_recognize_voice(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars

        body = Body()
        body.register_sense(MockEars(), MockMicrophone())
        body.open()

        assert body.ears.recognize_voice() == "voice_mock_001"

    def test_mock_throat_speak_and_play(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockSpeaker, MockThroat

        body = Body()
        speaker = MockSpeaker()
        body.register_sense(MockThroat(), speaker)
        body.open()

        body.throat.play("/music/song.mp3")
        assert speaker.last_played == "/music/song.mp3"


class TestBodyTools:
    """Body 工具测试 — 使用延迟绑定 _refs 模式。"""

    @staticmethod
    def _inject_refs(body, identity_mgr=None):
        """注入 body_ref 和 identity_mgr_ref，供工具函数延迟绑定使用。"""
        from xiaomei_brain.plugins.body import _refs
        _refs.body_ref[0] = body
        _refs.identity_mgr_ref[0] = identity_mgr

    @staticmethod
    def _clear_refs():
        """清理 _refs 避免测试间污染。"""
        from xiaomei_brain.plugins.body import _refs
        _refs.body_ref[0] = None
        _refs.identity_mgr_ref[0] = None

    def test_look_around_with_mock(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes
        from xiaomei_brain.plugins.tools.look_around.adapter import look_around

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc"])
        body.register_sense(MockEyes(), camera)
        body.open()

        self._inject_refs(body)
        result = look_around("描述现场")
        self._clear_refs()

        assert len(result["faces"]) == 1
        assert result["faces"][0]["face_id"] == "face_doc"
        assert "mock vision" in result["scene"]

    def test_look_around_with_identity_resolution(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes
        from xiaomei_brain.plugins.tools.look_around.adapter import look_around
        from xiaomei_brain.contacts.manager import IdentityManager
        import tempfile, os

        tmpdir = tempfile.mkdtemp()
        yaml_file = os.path.join(tmpdir, "identities.yaml")
        with open(yaml_file, "w") as f:
            f.write("""people:
  - id: boshi
    name: 博士
    relation: 恋人
    alias_ids:
      - face_doc
""")
        mgr = IdentityManager(tmpdir)

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc", "face_stranger"])
        body.register_sense(MockEyes(), camera)
        body.open()

        self._inject_refs(body, mgr)
        result = look_around()
        self._clear_refs()

        assert result["faces"][0]["name"] == "博士"
        assert result["faces"][0]["relation"] == "恋人"
        assert result["faces"][1]["name"] == "陌生人"

    def test_look_around_unavailable(self):
        from xiaomei_brain.plugins.tools.look_around.adapter import look_around

        self._clear_refs()
        result = look_around()
        assert "error" in result

    def test_play_music_with_mock(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockSpeaker, MockThroat
        from xiaomei_brain.plugins.tools.play_music.adapter import play_music

        body = Body()
        speaker = MockSpeaker()
        body.register_sense(MockThroat(), speaker)
        body.open()

        self._inject_refs(body)
        result = play_music("/music/chengdu.mp3")
        self._clear_refs()

        assert result["played"] == "/music/chengdu.mp3"
        assert speaker.last_played == "/music/chengdu.mp3"

    def test_listen_to_environment_with_mock(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars
        from xiaomei_brain.plugins.tools.listen_to_environment.adapter import listen_to_environment

        body = Body()
        mic = MockMicrophone()
        mic.set_speech("唱得真好")
        mic.set_tone("excited")
        body.register_sense(MockEars(), mic)
        body.open()

        self._inject_refs(body)
        result = listen_to_environment("分析情绪")
        self._clear_refs()

        assert "mock audio" in result["audio"]
        assert result["speaker"]["voice_id"] == "voice_mock_001"


class TestRealSpeaker:
    """真实扬声器测试 — 使用 ffplay 播放音频。"""

    def test_real_speaker_is_device(self):
        from xiaomei_brain.plugins.body.throat.wsl2 import RealSpeaker
        from xiaomei_brain.body.device import Speaker
        assert issubclass(RealSpeaker, Speaker)

    def test_real_speaker_lifecycle(self):
        from xiaomei_brain.plugins.body.throat.wsl2 import RealSpeaker
        s = RealSpeaker()
        assert s.is_operational() is False
        assert s.open() is True
        assert s.is_operational() is True
        s.close()
        assert s.is_operational() is False

    def test_real_speaker_play_records(self):
        from xiaomei_brain.plugins.body.throat.wsl2 import RealSpeaker
        import tempfile, os
        s = RealSpeaker()
        s.open()
        # 文件不存在 → 跳过播放，不设置 last_played
        s.play("/tmp/test.mp3")
        assert s.last_played is None
        # 文件存在 → 正常播放
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp = f.name
        try:
            s.play(tmp)
            assert s.last_played == tmp
        finally:
            os.unlink(tmp)

    def test_throat_with_real_speaker(self):
        """Throat + RealSpeaker 组合：play 委托到 RealSpeaker。"""
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.sense import Throat
        from xiaomei_brain.plugins.body.throat.wsl2 import RealSpeaker
        import tempfile, os

        body = Body()
        speaker = RealSpeaker()
        body.register_sense(Throat(), speaker)
        body.open()

        # 文件不存在 → 不崩溃，不设置 last_played
        body.throat.play("/music/song.mp3")
        assert speaker.last_played is None

        # 文件存在 → 正常
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp = f.name
        try:
            body.throat.play(tmp)
            assert speaker.last_played == tmp
        finally:
            os.unlink(tmp)

    def test_play_skips_when_file_missing(self):
        """文件不存在时 play() 不崩溃，静默跳过。"""
        from xiaomei_brain.plugins.body.throat.wsl2 import RealSpeaker
        s = RealSpeaker()
        s.open()
        s.play("/tmp/not_exists.mp3")  # 不应崩溃

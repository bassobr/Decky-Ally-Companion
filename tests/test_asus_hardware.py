
from allydsp import asus_fetch, hardware

API = {"Result": {"Obj": [{"Name": "Audio", "Files": [
    {"Title": "Dolby Atmos driver", "Version": "V10.1226.518.54", "ReleaseDate": "2026/01/16",
     "DownloadUrl": {"Global": "/pub/ASUS/old.exe", "China": None}, "sha256": "AB" * 32, "FileSize": "10.33 MB"},
    {"Title": "Dolby Atmos driver", "Version": "V11.130.1340.46", "ReleaseDate": "2026/02/25",
     "DownloadUrl": {"Global": "/pub/ASUS/new.exe"}, "sha256": "CD" * 32, "FileSize": "10.33 MB"},
    {"Title": "Realtek Audio Driver", "Version": "V6", "ReleaseDate": "2026/03/01", "DownloadUrl": {"Global": "/x.exe"}},
]}]}}


def test_parse_api_picks_newest_dolby_entry():
    pick = asus_fetch.parse_api(API, "https://dlcdnets.asus.com")
    assert pick["version"] == "V11.130.1340.46"
    assert pick["url"] == "https://dlcdnets.asus.com/pub/ASUS/new.exe"
    assert pick["sha256"] == "cd" * 32
    assert asus_fetch.parse_api({"Result": {}}, "x") is None


def test_find_7z_offset_across_chunk_boundary(tmp_path):
    p = tmp_path / "blob.bin"
    data = b"A" * 1000 + asus_fetch.SIG_7Z + b"B" * 100
    p.write_bytes(data)
    assert asus_fetch.find_7z_offset(str(p), chunk=64) == 1000
    assert asus_fetch.find_7z_offset(str(p), chunk=1003) == 1000  # signature split at the chunk edge
    (tmp_path / "none.bin").write_bytes(b"Z" * 5000)
    assert asus_fetch.find_7z_offset(str(tmp_path / "none.bin"), chunk=64) is None


def test_select_paths():
    entries = ["ext/x v1/dax3_ext_rtk.inf", "ext/x v1/DEV_0294_SUBSYS_10431384_PCI_SUBSYS_13841043.xml",
               "ext/x v1/DEV_0294_SUBSYS_10431384_settings.xml", "ext/x v1/DEV_0294_SUBSYS_10431394_PCI.xml"]
    sel = asus_fetch.select_paths(entries, "0294", "10431384")
    assert sel["xml"].endswith("13841043.xml") and sel["inf"].endswith("dax3_ext_rtk.inf")
    assert asus_fetch.select_paths(entries, "0287", "10431384")["xml"] is None


def test_codec_header_parse():
    head = "Codec: Realtek ALC294\nAddress: 0\nVendor Id: 0x10ec0294\nSubsystem Id: 0x10431384\n"
    assert hardware.parse_codec_header(head) == {"codec": "Realtek ALC294", "vendor_id": "10ec0294", "ssid": "10431384"}
    assert hardware.parse_codec_header("Codec: x\n") is None


DUMP = [
    {"id": 68, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink",
        "node.name": "alsa_loopback_device.alsa_output.pci-0000_64_00.6.analog-stereo"}}},
    {"id": 69, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink",
        "node.name": "alsa_output.pci-0000_64_00.6.analog-stereo", "node.description": "Ryzen HD Audio",
        "alsa.card_name": "HD-Audio Generic"}}},
    {"id": 64, "type": "PipeWire:Interface:Device", "info": {"props": {"device.api": "alsa",
        "device.name": "alsa_card.pci-0000_64_00.6"}, "params": {
        "EnumRoute": [{"name": "analog-output-speaker"}, {"name": "analog-output-headphones"}],
        "Route": [{"direction": "Input", "name": "analog-input-internal-mic"},
                  {"direction": "Output", "name": "analog-output-headphones", "description": "Headphones", "available": "yes"}]}}},
    {"id": 90, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": "effect_input.ally_companion_dsp"}}},
]


def test_pw_dump_helpers():
    sink = hardware.find_speaker_sink(DUMP)
    assert sink["name"] == "alsa_output.pci-0000_64_00.6.analog-stereo" and sink["id"] == 69
    route = hardware.output_route(DUMP)
    assert route["name"] == "analog-output-headphones" and hardware.headphones_active(route)
    assert hardware.filter_node_present(DUMP)
    assert not hardware.filter_node_present(DUMP[:-1])

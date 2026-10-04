import pytest

from allydsp import confgen
from allydsp.constants import INPUT_NODE, OUTPUT_NODE, SMART_FILTER_NAME

SYNTH = '''# converter comment with "quotes" and { braces }
context.modules = [
    {
        name = "libpipewire-module-filter-chain"
        flags = [ "ifexists" "nofail" ]
        args = {
            node.description = "Dolby-Balanced (speaker filter)"
            media.name = "Dolby-Balanced (speaker filter)"
            filter.graph = {
                nodes = [ {
                    type = "builtin"
                    name = "conv_l"
                    label = "convolver"
                    config = {
                        filename = "/tmp/out/Dolby_Balanced.irs"
                        channel = 0
                        gain = 1
                    }
                } {
                    type = "lv2"
                    name = "reg"
                    plugin = "http://lsp-plug.in/plugins/lv2/mb_compressor_stereo"
                    control = {
                        g_in = 1.995262315
                    }
                } {
                    type = "lv2"
                    name = "limiter"
                    plugin = "http://lsp-plug.in/plugins/lv2/limiter_stereo"
                    control = {
                        g_in = 1
                        g_out = 1
                    }
                } ]
                links = [ { output = "conv_l:Out" input = "reg:in_l" } ]
                inputs = [ "conv_l:In" ]
                outputs = [ "limiter:out_l" ]
            }
            capture.props = {
                node.name = "effect_input.Dolby_Balanced"
                media.class = "Audio/Sink"
                node.link-group = "Dolby_Balanced_smart_filter"
                filter.smart = true
                filter.smart.name = "Dolby_Balanced"
                filter.smart.target = {
                    node.name = "alsa_output.pci-0000_64_00.6.analog-stereo"
                }
                priority.session = -1
            }
            playback.props = {
                node.name = "effect_output.Dolby_Balanced"
                node.passive = true
                node.link-group = "Dolby_Balanced_smart_filter"
            }
        }
    }
]
'''


def test_finalize_rewrites_names_paths_and_target():
    out = confgen.finalize(SYNTH, "/home/deck/homebrew/data/Ally DSP/active/ir.irs", "Ally DSP: Game (Balanced)",
                           "alsa_output.pci-0000_aa_00.6.analog-stereo", "meta line")
    assert 'filename = "/home/deck/homebrew/data/Ally DSP/active/ir.irs"' in out
    assert f'node.name = "{INPUT_NODE}"' in out and f'node.name = "{OUTPUT_NODE}"' in out
    assert 'node.link-group = "ally_companion_dsp"' in out and "Dolby_Balanced_smart_filter" not in out
    assert f'filter.smart.name = "{SMART_FILTER_NAME}"' in out
    assert 'node.name = "alsa_output.pci-0000_aa_00.6.analog-stereo"' in out
    assert "alsa_output.pci-0000_64_00.6" not in out
    assert 'node.description = "Ally DSP: Game (Balanced)"' in out
    assert "libpipewire-module-protocol-native" in out and "libpipewire-module-adapter" in out
    assert out.count("libpipewire-module-filter-chain") == 1
    assert "# meta line" in out
    assert "converter comment" not in out  # comments stripped


def test_pregain_scales_only_the_limiter():
    out = confgen.finalize(SYNTH, "/x/ir.irs", "d", "sink", "c")
    assert confgen.limiter_input_gain(out) == 1.0
    scaled, ok = confgen.set_pregain_db(out, 6.0)
    assert ok
    assert confgen.limiter_input_gain(scaled) == pytest.approx(1.99526, rel=1e-4)
    assert "g_in = 1.995262315" in scaled  # multiband compressor untouched
    again, _ = confgen.set_pregain_db(scaled, 6.0, base_gain=1.0)
    assert confgen.limiter_input_gain(again) == pytest.approx(1.99526, rel=1e-4)


def test_missing_target_raises():
    with pytest.raises(ValueError):
        confgen.finalize(SYNTH.replace("filter.smart.target", "filter.other"), "/x", "d", "s", "c")
    with pytest.raises(ValueError):
        confgen.extract_module_block("nothing here")

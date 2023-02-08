# coding=utf-8
import os
import re
import utils
import commons
import json
import gradio as gr
from models import SynthesizerTrn
from text import text_to_sequence
from torch import no_grad, LongTensor
import logging
logging.getLogger('numba').setLevel(logging.WARNING)
hps_ms = utils.get_hparams_from_file(r'config/config.json')

def get_text(text, hps):
    text_norm, clean_text = text_to_sequence(text, hps.symbols, hps.data.text_cleaners)
    if hps.data.add_blank:
        text_norm = commons.intersperse(text_norm, 0)
    text_norm = LongTensor(text_norm)
    return text_norm, clean_text

def create_tts_fn(net_g_ms, speaker_id):
    def tts_fn(text, language, noise_scale, noise_scale_w, length_scale):
        text = text.replace('\n', ' ').replace('\r', '').replace(" ", "")
        text_len = len(re.sub("\[([A-Z]{2})\]", "", text))
        max_len = 150
        if text_len > max_len:
            return "Error: Text is too long", None
        if language == 0:
            text = f"[ZH]{text}[ZH]"
        elif language == 1:
            text = f"[JA]{text}[JA]"
        else:
            text = f"{text}"
        stn_tst, clean_text = get_text(text, hps_ms)
        with no_grad():
            x_tst = stn_tst.unsqueeze(0)
            x_tst_lengths = LongTensor([stn_tst.size(0)])
            sid = LongTensor([speaker_id])
            audio = net_g_ms.infer(x_tst, x_tst_lengths, sid=sid, noise_scale=noise_scale, noise_scale_w=noise_scale_w,
                                   length_scale=length_scale)[0][0, 0].data.float().numpy()

        return "Success", (22050, audio)
    return tts_fn

def change_lang(language):
    if language == 0:
        return 0.6, 0.668, 1.2
    else:
        return 0.6, 0.668, 1

download_audio_js = """
() =>{{
    let root = document.querySelector("body > gradio-app");
    if (root.shadowRoot != null)
        root = root.shadowRoot;
    let audio = root.querySelector("#tts-audio").querySelector("audio");
    let text = root.querySelector("#input-text").querySelector("textarea");
    if (audio == undefined)
        return;
    text = text.value;
    if (text == undefined)
        text = Math.floor(Math.random()*100000000);
    audio = audio.src;
    let oA = document.createElement("a");
    oA.download = text.substr(0, 20)+'.wav';
    oA.href = audio;
    document.body.appendChild(oA);
    oA.click();
    oA.remove();
}}
"""

if __name__ == '__main__':
    models = []
    with open("pretrained_models/info.json", "r", encoding="utf-8") as f:
        models_info = json.load(f)
    for i, info in models_info.items():
        net_g_ms = SynthesizerTrn(
            len(hps_ms.symbols),
            hps_ms.data.filter_length // 2 + 1,
            hps_ms.train.segment_size // hps_ms.data.hop_length,
            n_speakers=hps_ms.data.n_speakers,
            **hps_ms.model)
        _ = net_g_ms.eval()
        sid = info['sid']
        name_en = info['name_en']
        name_zh = info['name_zh']
        title = info['title']
        cover = f"pretrained_models/{i}/{info['cover']}"
        utils.load_checkpoint(f'pretrained_models/{i}/{i}.pth', net_g_ms, None)
        models.append((sid, name_en, name_zh, title, cover, net_g_ms, create_tts_fn(net_g_ms, sid)))
    with gr.Blocks() as app:
        gr.Markdown(
            "# <center> vits-models\n"
            "![visitor badge](https://visitor-badge.glitch.me/badge?page_id=sayashi.vits-models)\n\n"
        )

        with gr.Tabs():
            with gr.TabItem("EN"):
                for (sid, name_en, name_zh, title, cover, net_g_ms, tts_fn) in models:
                    with gr.TabItem(name_en):
                        with gr.Row():
                            gr.Markdown(
                                '<div align="center">'
                                f'<a><strong>{title}</strong></a>'
                                f'<img style="width:auto;height:300px;" src="file/{cover}">' if cover else ""
                                '</div>'
                            )
                        with gr.Row():
                            with gr.Column():
                                input_text = gr.Textbox(label="Text (100 words limitation)", lines=5, value="先生。今日も全力であなたをアシストしますね。", elem_id=f"input-text")
                                lang = gr.Dropdown(label="Language", choices=["Chinese", "Japanese", "Mix（wrap the Chinese text with [ZH][ZH], wrap the Japanese text with [JA][JA]）"],
                                            type="index", value="Japanese")
                                btn = gr.Button(value="Generate")
                                with gr.Row():
                                    ns = gr.Slider(label="noise_scale", minimum=0.1, maximum=1.0, step=0.1, value=0.6, interactive=True)
                                    nsw = gr.Slider(label="noise_scale_w", minimum=0.1, maximum=1.0, step=0.1, value=0.668, interactive=True)
                                    ls = gr.Slider(label="length_scale", minimum=0.1, maximum=2.0, step=0.1, value=1, interactive=True)
                            with gr.Column():
                                o1 = gr.Textbox(label="Output Message")
                                o2 = gr.Audio(label="Output Audio", elem_id=f"tts-audio")
                                download = gr.Button("Download Audio")
                            btn.click(tts_fn, inputs=[input_text, lang,  ns, nsw, ls], outputs=[o1, o2])
                            download.click(None, [], [], _js=download_audio_js.format())
                            lang.change(change_lang, inputs=[lang], outputs=[ns, nsw, ls])
            with gr.TabItem("中文"):
                for (sid, name_en, name_zh, title, cover, net_g_ms, tts_fn) in models:
                    with gr.TabItem(name_zh):
                        with gr.Row():
                            gr.Markdown(
                                '<div align="center">'
                                f'<a><strong>{title}</strong></a>'
                                f'<img style="width:auto;height:300px;" src="file/{cover}">' if cover else ""
                                '</div>'
                            )
                        with gr.Row():
                            with gr.Column():
                                input_text = gr.Textbox(label="文本 (100字上限)", lines=5, value="先生。今日も全力であなたをアシストしますね。", elem_id=f"input-text")
                                lang = gr.Dropdown(label="语言", choices=["中文", "日语", "中日混合（中文用[ZH][ZH]包裹起来，日文用[JA][JA]包裹起来）"],
                                            type="index", value="日语")
                                btn = gr.Button(value="生成")
                                with gr.Row():
                                    ns = gr.Slider(label="控制感情变化程度", minimum=0.1, maximum=1.0, step=0.1, value=0.6, interactive=True)
                                    nsw = gr.Slider(label="控制音素发音长度", minimum=0.1, maximum=1.0, step=0.1, value=0.668, interactive=True)
                                    ls = gr.Slider(label="控制整体语速", minimum=0.1, maximum=2.0, step=0.1, value=1, interactive=True)
                            with gr.Column():
                                o1 = gr.Textbox(label="输出信息")
                                o2 = gr.Audio(label="输出音频", elem_id=f"tts-audio")
                                download = gr.Button("下载音频")
                            btn.click(tts_fn, inputs=[input_text, lang,  ns, nsw, ls], outputs=[o1, o2])
                            download.click(None, [], [], _js=download_audio_js.format())
                            lang.change(change_lang, inputs=[lang], outputs=[ns, nsw, ls])
    app.queue(concurrency_count=1).launch()

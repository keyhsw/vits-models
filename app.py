# coding=utf-8
import os
import re
import argparse
import utils
import commons
import json
import torch
import gradio as gr
from models import SynthesizerTrn
from text import text_to_sequence
from torch import no_grad, LongTensor
import gradio.processing_utils as gr_processing_utils
import logging
logging.getLogger('numba').setLevel(logging.WARNING)
limitation = os.getenv("SYSTEM") == "spaces"  # limit text and audio length in huggingface spaces

hps_ms = utils.get_hparams_from_file(r'config/config.json')

audio_postprocess_ori = gr.Audio.postprocess

def audio_postprocess(self, y):
    data = audio_postprocess_ori(self, y)
    if data is None:
        return None
    return gr_processing_utils.encode_url_or_file_to_base64(data["name"])


gr.Audio.postprocess = audio_postprocess

def get_text(text, hps):
    text_norm, clean_text = text_to_sequence(text, hps.symbols, hps.data.text_cleaners)
    if hps.data.add_blank:
        text_norm = commons.intersperse(text_norm, 0)
    text_norm = LongTensor(text_norm)
    return text_norm, clean_text

def create_tts_fn(net_g_ms, speaker_id):
    def tts_fn(text, language, noise_scale, noise_scale_w, length_scale):
        text = text.replace('\n', ' ').replace('\r', '').replace(" ", "")
        if limitation:
            text_len = len(re.sub("\[([A-Z]{2})\]", "", text))
            max_len = 100
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
            x_tst = stn_tst.unsqueeze(0).to(device)
            x_tst_lengths = LongTensor([stn_tst.size(0)]).to(device)
            sid = LongTensor([speaker_id]).to(device)
            audio = net_g_ms.infer(x_tst, x_tst_lengths, sid=sid, noise_scale=noise_scale, noise_scale_w=noise_scale_w,
                                   length_scale=length_scale)[0][0, 0].data.cpu().float().numpy()

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
    let audio = root.querySelector("#tts-audio-{audio_id}").querySelector("audio");
    let text = root.querySelector("#input-text-{audio_id}").querySelector("textarea");
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', type=str, default='cpu')
    parser.add_argument("--share", action="store_true", default=False, help="share gradio app")
    args = parser.parse_args()
    device = torch.device(args.device)
    
    models = []
    with open("pretrained_models/info.json", "r", encoding="utf-8") as f:
        models_info = json.load(f)
    for i, info in models_info.items():
        sid = info['sid']
        name_en = info['name_en']
        name_zh = info['name_zh']
        title = info['title']
        cover = f"pretrained_models/{i}/{info['cover']}"
        example = info['example']
        language = info['language']
        net_g_ms = SynthesizerTrn(
            len(hps_ms.symbols),
            hps_ms.data.filter_length // 2 + 1,
            hps_ms.train.segment_size // hps_ms.data.hop_length,
            n_speakers=hps_ms.data.n_speakers if info['type'] == "multi" else 0,
            **hps_ms.model)
        utils.load_checkpoint(f'pretrained_models/{i}/{i}.pth', net_g_ms, None)
        _ = net_g_ms.eval().to(device)
        models.append((sid, name_en, name_zh, title, cover, example, language, net_g_ms, create_tts_fn(net_g_ms, sid)))
    with gr.Blocks() as app:
        gr.Markdown(
            "# <center> vits-models\n"
            "## <center> Please do not generate content that could infringe upon the rights or cause harm to individuals or organizations.\n"
            "## <center> 请不要生成会对个人以及组织造成侵害的内容\n"
            "![visitor badge](https://visitor-badge.glitch.me/badge?page_id=sayashi.vits-models)\n\n"
            "[Open In Colab]"
            "(https://colab.research.google.com/drive/10QOk9NPgoKZUXkIhhuVaZ7SYra1MPMKH?usp=share_link)"
            " without queue and length limitation.(无需等待队列，并且没有长度限制)\n\n"
            "[Finetune your own model](https://github.com/SayaSS/vits-finetuning)"
        )

        with gr.Tabs():
            with gr.TabItem("EN"):
                for (sid, name_en, name_zh, title, cover, example, language, net_g_ms, tts_fn) in models:
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
                                input_text = gr.Textbox(label="Text (100 words limitation)", lines=5, value=example, elem_id=f"input-text-en-{name_en.replace(' ','')}")
                                lang = gr.Dropdown(label="Language", choices=["Chinese", "Japanese", "Mix（wrap the Chinese text with [ZH][ZH], wrap the Japanese text with [JA][JA]）"],
                                            type="index", value=language)
                                btn = gr.Button(value="Generate")
                                with gr.Row():
                                    ns = gr.Slider(label="noise_scale", minimum=0.1, maximum=1.0, step=0.1, value=0.6, interactive=True)
                                    nsw = gr.Slider(label="noise_scale_w", minimum=0.1, maximum=1.0, step=0.1, value=0.668, interactive=True)
                                    ls = gr.Slider(label="length_scale", minimum=0.1, maximum=2.0, step=0.1, value=1.2 if language=="Chinese" else 1, interactive=True)
                            with gr.Column():
                                o1 = gr.Textbox(label="Output Message")
                                o2 = gr.Audio(label="Output Audio", elem_id=f"tts-audio-en-{name_en.replace(' ','')}")
                                download = gr.Button("Download Audio")
                            btn.click(tts_fn, inputs=[input_text, lang,  ns, nsw, ls], outputs=[o1, o2])
                            download.click(None, [], [], _js=download_audio_js.format(audio_id=f"en-{name_en.replace(' ','')}"))
                            lang.change(change_lang, inputs=[lang], outputs=[ns, nsw, ls])
            with gr.TabItem("中文"):
                for (sid, name_en, name_zh, title, cover, example, language,  net_g_ms, tts_fn) in models:
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
                                input_text = gr.Textbox(label="文本 (100字上限)", lines=5, value=example, elem_id=f"input-text-zh-{name_zh}")
                                lang = gr.Dropdown(label="语言", choices=["中文", "日语", "中日混合（中文用[ZH][ZH]包裹起来，日文用[JA][JA]包裹起来）"],
                                            type="index", value="中文"if language == "Chinese" else "日语")
                                btn = gr.Button(value="生成")
                                with gr.Row():
                                    ns = gr.Slider(label="控制感情变化程度", minimum=0.1, maximum=1.0, step=0.1, value=0.6, interactive=True)
                                    nsw = gr.Slider(label="控制音素发音长度", minimum=0.1, maximum=1.0, step=0.1, value=0.668, interactive=True)
                                    ls = gr.Slider(label="控制整体语速", minimum=0.1, maximum=2.0, step=0.1, value=1.2 if language=="Chinese" else 1, interactive=True)
                            with gr.Column():
                                o1 = gr.Textbox(label="输出信息")
                                o2 = gr.Audio(label="输出音频", elem_id=f"tts-audio-zh-{name_zh}")
                                download = gr.Button("下载音频")
                            btn.click(tts_fn, inputs=[input_text, lang,  ns, nsw, ls], outputs=[o1, o2])
                            download.click(None, [], [], _js=download_audio_js.format(audio_id=f"zh-{name_zh}"))
                            lang.change(change_lang, inputs=[lang], outputs=[ns, nsw, ls])
    app.queue(concurrency_count=1).launch(show_api=False, share=args.share)

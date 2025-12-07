import xml.etree.ElementTree as ET
import json
import os
import uuid
import urllib.parse
import difflib
import re
import unicodedata

# --- CONFIGURAÇÕES GERAIS ---
ARQUIVO_SAIDA = 'TIMELINE_FINAL_TEXT_BASED_V1.5.2.xml'
WIDTH = 1920
HEIGHT = 1080
TIMEBASE_XML = 30
IS_NTSC = "TRUE"

# --- CONFIGURAÇÃO DE "GORDURA" (HANDLES) ---
SEGUNDOS_GORDURA_IN = 1.5
SEGUNDOS_GORDURA_OUT = 1.5

# --- UTILITÁRIOS DE TEXTO ---

def normalizar_texto_profundo(texto):
    if not texto:
        return ""
    texto = texto.lower()
    nfkd_form = unicodedata.normalize('NFKD', texto)
    texto = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

# --- FUNÇÕES DE INFRAESTRUTURA ---

def gerar_chave_unificada(nome):
    if not nome:
        return ""
    return os.path.splitext(nome.strip().lower())[0]

def validar_caminho(nome_arquivo, caminho_bruto):
    if not caminho_bruto:
        return ""
    
    caminho_limpo = urllib.parse.unquote(caminho_bruto)
    if caminho_limpo.startswith("file://localhost"):
        caminho_limpo = caminho_limpo[16:]
    elif caminho_limpo.startswith("file://"):
        caminho_limpo = caminho_limpo[7:]
    
    _, ext_nome = os.path.splitext(nome_arquivo.lower())
    _, ext_path = os.path.splitext(caminho_limpo.lower())
    
    if ext_nome in ['.mov', '.mxf', '.mp4', '.wav', '.aif', '.bwf', '.mp3'] and not ext_path:
        _, ext_nome_real = os.path.splitext(nome_arquivo)
        return caminho_limpo + ext_nome_real
        
    return caminho_limpo

def analisar_timeline_original(caminho_xml):
    if not caminho_xml:
        return [], {}, {}, 30.0, 1920, 1080
    
    print(f"   -> Analisando XML Original: {os.path.basename(caminho_xml)}")
    
    try:
        tree = ET.parse(caminho_xml)
        root = tree.getroot()
    except:
        return [], {}, {}, 30.0, 1920, 1080

    fps = 30.0
    width = 1920
    height = 1080
    
    try:
        seq_node = root.find(".//sequence")
        if seq_node is not None:
            rate = seq_node.find("rate")
            if rate is not None:
                tb = int(rate.find("timebase").text)
                ntsc = rate.find("ntsc")
                if ntsc is not None and ntsc.text == 'TRUE' and tb == 30:
                    fps = 29.97
                else:
                    fps = float(tb)
            
            fmt = seq_node.find(".//media/video/format/samplecharacteristics")
            if fmt is not None:
                w = fmt.find("width")
                h = fmt.find("height")
                if w is not None:
                    width = int(w.text)
                if h is not None:
                    height = int(h.text)
    except:
        pass
    
    print(f"      -> Formato Detectado: {width}x{height} @ {fps}fps")

    file_db = {}
    for f in root.findall(".//file"):
        fid = f.get('id')
        name = f.find('name')
        path = f.find('pathurl')
        ch = 2
        try:
            c = f.find(".//media/audio/samplecharacteristics/channelcount")
            if c is not None:
                ch = max(2, int(c.text))
        except:
            pass
            
        if fid and name is not None:
            fn = name.text.strip()
            fp = validar_caminho(fn, path.text if path is not None else "")
            file_db[fid] = {'name': fn, 'path': fp, 'channels': ch}

    video_events = []
    audio_events = []
    timeline_clips = [] 
    
    for track in root.findall(".//video/track"):
        for clip in track.findall("clipitem"):
            start = clip.find('start')
            end = clip.find('end')
            in_src = clip.find('in')
            out_src = clip.find('out')
            fid = clip.find('file')
            
            if start is not None and fid is not None:
                fid_val = fid.get('id')
                if fid_val in file_db:
                    fdata = file_db[fid_val]
                    video_events.append({
                        'name': fdata['name'],
                        'start': int(start.text),
                        'end': int(end.text),
                        'in': int(in_src.text),
                        'fid': fid_val,
                        'path': fdata['path'],
                        'data': fdata
                    })
                    timeline_clips.append({
                        'tl_start': int(start.text),
                        'tl_end': int(end.text),
                        'src_in': int(in_src.text),
                        'src_out': int(out_src.text),
                        'file_data': fdata
                    })

    track_counter = 0
    for track in root.findall(".//audio/track"):
        track_counter += 1
        for clip in track.findall("clipitem"):
            start = clip.find('start')
            end = clip.find('end')
            in_src = clip.find('in')
            fid = clip.find('file')
            
            if start is not None and fid is not None:
                fid_val = fid.get('id')
                if fid_val in file_db:
                    audio_events.append({
                        'name': file_db[fid_val]['name'],
                        'start': int(start.text),
                        'end': int(end.text),
                        'in': int(in_src.text),
                        'track': track_counter,
                        'fid': fid_val,
                        'path': file_db[fid_val]['path'],
                        'data': file_db[fid_val]
                    })

    timeline_clips.sort(key=lambda x: x['tl_start'])

    sync_map = {}
    total_pares = 0
    
    for v in video_events:
        v_key = gerar_chave_unificada(v['name'])
        if v_key not in sync_map:
            sync_map[v_key] = []
        
        for a in audio_events:
            if a['fid'] == v['fid']: continue 
            if a['path'] == v['path']: continue 
            
            is_wav = a['name'].lower().endswith(('.wav', '.bwf', '.aif', '.mp3'))
            if not is_wav and gerar_chave_unificada(a['name']) == v_key:
                continue

            overlap_start = max(v['start'], a['start'])
            overlap_end = min(v['end'], a['end'])
            
            if overlap_start < overlap_end:
                delta = (a['in'] + (v['start'] - a['start'])) - v['in']
                exists = False
                for item in sync_map[v_key]:
                    if item['path'] == a['path']:
                        exists = True
                
                if not exists:
                    sync_map[v_key].append({
                        'name': a['name'],
                        'path': a['data']['path'],
                        'channels': a['data']['channels'],
                        'track': a['track'],
                        'delta': delta
                    })
                    total_pares += 1

    print(f"      -> {total_pares} pares de áudio externo mapeados.")
    return timeline_clips, sync_map, file_db, fps, width, height

# --- FUZZY HUNTER ---

def carregar_banco_palavras(caminho_json, fps_real):
    print(f"   -> Indexando palavras do JSON: {os.path.basename(caminho_json)}")
    try:
        with open(caminho_json, 'r', encoding='utf-8') as f:
            dados = json.load(f)
    except:
        return [], "", []

    ts_list = []
    def extract_ts(d):
        if isinstance(d, dict):
            t = d.get('ts') or d.get('start') or d.get('startTime')
            if t is not None:
                ts_list.append(float(t))
            for v in d.values(): 
                if isinstance(v, (dict, list)):
                    extract_ts(v)
        elif isinstance(d, list):
            for i in d:
                extract_ts(i)
    
    extract_ts(dados)
    
    fator = 1.0
    if ts_list and max(ts_list) > 500000:
        fator = 0.001 

    palavras_db = []
    lista_normalizada = []
    
    def extract_words(d):
        if isinstance(d, dict):
            txt = d.get('text') or d.get('content')
            ts = d.get('ts') or d.get('start') or d.get('startTime')
            end = d.get('end_ts') or d.get('end') or d.get('endTime')
            
            if txt and ts is not None:
                start_sec = float(ts) * fator
                end_sec = (float(end) * fator) if end else (start_sec + 0.5)
                
                palavras_db.append({
                    'texto': txt.strip(),
                    'tl_start_f': int(start_sec * fps_real),
                    'tl_end_f': int(end_sec * fps_real)
                })
                lista_normalizada.append(normalizar_texto_profundo(txt))

            for v in d.values(): 
                if isinstance(v, (dict, list)):
                    extract_words(v)
        elif isinstance(d, list):
            for i in d:
                extract_words(i)
            
    extract_words(dados)
    string_mestra_norm = " ".join(lista_normalizada)
    
    return palavras_db, string_mestra_norm, lista_normalizada

def encontrar_trecho_otimizado(texto_coutinho, string_mestra_norm, palavras_db, lista_normalizada):
    texto_alvo_norm = normalizar_texto_profundo(texto_coutinho)
    if not texto_alvo_norm:
        return None, None

    matcher = difflib.SequenceMatcher(None, string_mestra_norm, texto_alvo_norm)
    match = matcher.find_longest_match(0, len(string_mestra_norm), 0, len(texto_alvo_norm))
    
    if match.size < (len(texto_alvo_norm) * 0.5):
        return None, None

    palavras_alvo = texto_alvo_norm.split()
    if not palavras_alvo:
        return None, None
    
    n_palavras = len(palavras_alvo)
    primeira = palavras_alvo[0]
    
    melhor_score = 0
    melhor_inicio_idx = -1
    
    candidatos_inicio = [i for i, x in enumerate(lista_normalizada) if x == primeira]
    
    if not candidatos_inicio and n_palavras > 1:
        primeira = palavras_alvo[1]
        candidatos_inicio = [i for i, x in enumerate(lista_normalizada) if x == primeira]
        if candidatos_inicio:
            palavras_alvo = palavras_alvo[1:]
            n_palavras -= 1
        
    for idx in candidatos_inicio:
        score = 0
        for k in range(min(n_palavras, len(lista_normalizada) - idx)):
            if lista_normalizada[idx + k] == palavras_alvo[k]:
                score += 1
            else:
                if score < k * 0.7:
                    break 
        if score > melhor_score:
            melhor_score = score
            melhor_inicio_idx = idx

    if melhor_score > 0 and (melhor_score / n_palavras) > 0.6:
        p_inicio = palavras_db[melhor_inicio_idx]
        p_fim = palavras_db[min(melhor_inicio_idx + melhor_score, len(palavras_db)-1)]
        return p_inicio['tl_start_f'], p_fim['tl_end_f']

    return None, None

def localizar_midia_por_tempo(tl_in, tl_out, timeline_clips):
    for clip in timeline_clips:
        if (clip['tl_start'] <= tl_in + 5) and (clip['tl_end'] >= tl_out - 5):
            offset_in = tl_in - clip['tl_start']
            src_in_new = clip['src_in'] + offset_in
            src_out_new = src_in_new + (tl_out - tl_in)
            return {
                'file_data': clip['file_data'],
                'src_in': src_in_new,
                'src_out': src_out_new,
                'found': True
            }
    return None

# --- GERADOR XML ---

def criar_elem(tag, parent, text=None):
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e

def criar_rate(parent, timebase):
    r = ET.SubElement(parent, 'rate')
    criar_elem('timebase', r, timebase)
    criar_elem('ntsc', r, IS_NTSC)

def criar_link(parent, clip_ref_id, media_type, track_index, clip_index):
    l = ET.SubElement(parent, 'link')
    criar_elem('linkclipref', l, clip_ref_id)
    criar_elem('mediatype', l, media_type)
    criar_elem('trackindex', l, track_index)
    criar_elem('clipindex', l, clip_index)
    if media_type == "video":
        criar_elem('groupindex', l, 1)

def criar_clipitem(parent, id_clip, nome, start, end, in_, out_, file_id, path, track_idx, is_audio, channels=2, link_ids=None, width=1920, height=1080, clip_count=1):
    ci = ET.SubElement(parent, 'clipitem', {'id': id_clip})
    criar_elem('name', ci, nome)
    criar_elem('enabled', ci, "TRUE")
    criar_elem('duration', ci, end - start)
    criar_rate(ci, TIMEBASE_XML)
    criar_elem('start', ci, start)
    criar_elem('end', ci, end)
    criar_elem('in', ci, in_)
    criar_elem('out', ci, out_)
    
    f = ET.SubElement(ci, 'file', {'id': file_id})
    criar_elem('name', f, nome)
    if path:
        safe_path = urllib.parse.quote(path.replace("file://localhost", ""))
        if not safe_path.startswith('/'):
            safe_path = '/' + safe_path
        criar_elem('pathurl', f, f"file://localhost{safe_path}")
        
    criar_rate(f, TIMEBASE_XML)
    m = criar_elem('media', f)
    if not is_audio:
        v = criar_elem('video', m)
        sc = criar_elem('samplecharacteristics', v)
        criar_rate(sc, TIMEBASE_XML)
        criar_elem('width', sc, width)
        criar_elem('height', sc, height)
    
    a = criar_elem('audio', m)
    sc_a = criar_elem('samplecharacteristics', a)
    criar_elem('depth', sc_a, 16)
    criar_elem('samplerate', sc_a, 48000)
    criar_elem('channelcount', sc_a, channels)
    
    if is_audio:
        lnk = ET.SubElement(ci, 'sourcetrack')
        criar_elem('mediatype', lnk, 'audio')
        criar_elem('trackindex', lnk, track_idx)
    
    if link_ids:
        if 'video' in link_ids and link_ids['video'] != id_clip:
            criar_link(ci, link_ids['video'], "video", 1, clip_count)
        if 'a1' in link_ids and link_ids['a1'] != id_clip:
            criar_link(ci, link_ids['a1'], "audio", 1, clip_count)
        if 'a2' in link_ids and link_ids['a2'] != id_clip:
            criar_link(ci, link_ids['a2'], "audio", 2, clip_count)
        if 'ext_a1' in link_ids and link_ids['ext_a1'] != id_clip:
            criar_link(ci, link_ids['ext_a1'], "audio", 1, clip_count) 
        if 'ext_a2' in link_ids and link_ids['ext_a2'] != id_clip:
            criar_link(ci, link_ids['ext_a2'], "audio", 2, clip_count) 
    return ci

def main_hunter():
    print("--- CONFORMADOR TEXTO -> XML (V1.5.2 FINAL) ---")
    
    cwd = os.getcwd()
    f_json_coutinho = next((f for f in os.listdir(cwd) if 'Coutinho' in f and f.endswith('.json')), None)
    
    f_xml_orig = next((f for f in os.listdir(cwd) if f.lower().endswith('.xml') and ("limpa" in f.lower() or "limpo" in f.lower())), None)
    if not f_xml_orig:
        f_xml_orig = next((f for f in os.listdir(cwd) if f.lower().endswith('.xml') and not f.startswith('~$')), None)
        
    f_json_orig = next((f for f in os.listdir(cwd) if f.lower().endswith('.json') and not f.startswith('INPUT') and not f.startswith('Roteiro') and not f.startswith('~$')), None)
    
    if not all([f_json_coutinho, f_xml_orig, f_json_orig]):
        print("ERRO: Faltam arquivos.")
        return

    timeline_clips, sync_map, file_db_orig, fps_real, seq_w, seq_h = analisar_timeline_original(f_xml_orig)
    palavras_db, string_mestra_norm, lista_normalizada = carregar_banco_palavras(f_json_orig, fps_real)
    
    try:
        with open(f_json_coutinho, 'r', encoding='utf-8') as f:
            roteiro = json.load(f)
    except:
        print("Erro JSON Coutinho")
        return

    root = ET.Element('xmeml', {'version': '4'})
    seq = ET.SubElement(root, 'sequence')
    criar_elem('name', seq, "TIMELINE_TEXT_BASED_V1.5.2")
    criar_elem('uuid', seq, str(uuid.uuid4()))
    criar_rate(seq, TIMEBASE_XML)
    
    media = ET.SubElement(seq, 'media')
    vid = ET.SubElement(media, 'video')
    
    fmt = ET.SubElement(vid, 'format')
    sc = ET.SubElement(fmt, 'samplecharacteristics')
    criar_rate(sc, TIMEBASE_XML)
    criar_elem('width', sc, seq_w) 
    criar_elem('height', sc, seq_h)
    
    track_v = ET.SubElement(vid, 'track')
    aud = ET.SubElement(media, 'audio')
    tracks_audio_nodes = []
    for t in range(1, 13):
        ta = ET.SubElement(aud, 'track')
        criar_elem('outputchannelindex', ta, "1" if t % 2 != 0 else "2")
        tracks_audio_nodes.append(ta)
    
    cursor = 0
    clip_count = 0
    cache_fid = {}
    cache_audio_ext = {}
    missing_clips = []
    
    frames_gordura_in = int(SEGUNDOS_GORDURA_IN * fps_real)
    frames_gordura_out = int(SEGUNDOS_GORDURA_OUT * fps_real)
    print(f"   -> Adicionando handles: +{frames_gordura_in} frames IN / +{frames_gordura_out} frames OUT")

    for bloco in ['bloco_1', 'bloco_2']:
        itens = roteiro.get(bloco, [])
        print(f"   Processando {bloco} ({len(itens)} falas)...")
        
        for item in itens:
            texto = item.get('texto', '')
            if not texto: continue
            
            tl_in, tl_out = encontrar_trecho_otimizado(texto, string_mestra_norm, palavras_db, lista_normalizada)
            
            if tl_in is not None:
                match_media = localizar_midia_por_tempo(tl_in, tl_out, timeline_clips)
                
                if match_media:
                    fdata = match_media['file_data']
                    f_in_raw = match_media['src_in']
                    f_out_raw = match_media['src_out']
                    
                    # APLICAÇÃO GORDURA
                    f_in = max(0, f_in_raw - frames_gordura_in)
                    f_out = f_out_raw + frames_gordura_out
                    
                    duracao = f_out - f_in
                    if duracao <= 0: continue
                    
                    clip_count += 1
                    fname = fdata['name']
                    
                    if fname not in cache_fid:
                        cache_fid[fname] = {'fid': str(uuid.uuid4()), 'path': fdata['path'], 'channels': fdata['channels']}
                    cached = cache_fid[fname]
                    
                    chave_busca = gerar_chave_unificada(fname)
                    audios_encontrados = sync_map.get(chave_busca, [])
                    
                    tem_audio_externo = len(audios_encontrados) > 0
                    usar_cam_audio = not tem_audio_externo
                    
                    id_v = f"v-{clip_count}"
                    id_a1 = f"a1-{clip_count}"
                    id_a2 = f"a2-{clip_count}"
                    links = {'video': id_v}
                    if usar_cam_audio: links.update({'a1': id_a1, 'a2': id_a2})

                    # VIDEO
                    criar_clipitem(track_v, id_v, fname, cursor, cursor+duracao, f_in, f_out, cached['fid'], cached['path'], 1, False, cached['channels'], links, seq_w, seq_h, clip_count)
                    
                    # CAMERA
                    if usar_cam_audio:
                        criar_clipitem(tracks_audio_nodes[0], id_a1, fname, cursor, cursor+duracao, f_in, f_out, cached['fid'], cached['path'], 1, True, cached['channels'], links, 1920, 1080, clip_count)
                        criar_clipitem(tracks_audio_nodes[1], id_a2, fname, cursor, cursor+duracao, f_in, f_out, cached['fid'], cached['path'], 2, True, cached['channels'], links, 1920, 1080, clip_count)
                    
                    # EXTERNO
                    if tem_audio_externo:
                        curr_tk = 0 
                        for idx_ext, link_data in enumerate(audios_encontrados):
                            if curr_tk + 1 >= len(tracks_audio_nodes): break
                            
                            a_name = link_data['name']
                            a_path = validar_caminho(a_name, link_data['path']) 
                            a_ch = max(2, link_data['channels'])
                            delta = link_data['delta']
                            
                            a_in_new = f_in + delta
                            a_out_new = a_in_new + duracao
                            
                            k_aud = gerar_chave_unificada(a_name)
                            if k_aud not in cache_audio_ext:
                                cache_audio_ext[k_aud] = {'fid': str(uuid.uuid4()), 'path': a_path, 'channels': a_ch}
                            afdata = cache_audio_ext[k_aud]
                            
                            id_e1 = f"ext-{clip_count}-{idx_ext}L"
                            id_e2 = f"ext-{clip_count}-{idx_ext}R"
                            lnk_ext = {'ext_a1': id_e1, 'ext_a2': id_e2, 'video': id_v}
                            
                            criar_clipitem(tracks_audio_nodes[curr_tk], id_e1, a_name, cursor, cursor+duracao, a_in_new, a_out_new, afdata['fid'], afdata['path'], 1, True, a_ch, lnk_ext, 1920, 1080, clip_count)
                            criar_clipitem(tracks_audio_nodes[curr_tk+1], id_e2, a_name, cursor, cursor+duracao, a_in_new, a_out_new, afdata['fid'], afdata['path'], 2, True, a_ch, lnk_ext, 1920, 1080, clip_count)
                            curr_tk += 2

                    cursor += duracao
                else:
                    print(f"      [AVISO] Texto encontrado, mas sem mídia correspondente: {texto[:30]}...")
            else:
                missing_clips.append(texto[:50])

    total_s = cursor / fps_real
    print(f"\n   -> DURAÇÃO FINAL: {int(total_s//60)}min {int(total_s%60)}s")
    if missing_clips:
        print(f"   -> ⚠️ {len(missing_clips)} frases não encontradas.")

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding='utf-8').decode()
    with open(ARQUIVO_SAIDA, 'w', encoding='utf-8') as f: f.write(xml_str)
    print(f"SUCESSO! XML Gerado: {ARQUIVO_SAIDA}")

if __name__ == "__main__":
    main_hunter()
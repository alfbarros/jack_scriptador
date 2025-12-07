import json
import os
import re

# --- CONFIGURAÇÃO ---
ARQUIVO_SAIDA = "ROTEIRO_PARA_LEITURA_COUTINHO.txt"

def carregar_locutores_txt(caminho_txt):
    """Lê o TXT do Premiere (formato 3 linhas) para mapear quem fala quando."""
    if not caminho_txt: return []
    mapeamento = []
    try:
        with open(caminho_txt, 'r', encoding='utf-8') as f:
            linhas = f.readlines()
        
        # Regex para capturar intervalo de Timecode (HH:MM:SS:FF - HH:MM:SS:FF)
        regex_tc_range = re.compile(r'^(\d{2}:\d{2}:\d{2}[:;]\d{2})\s*-\s*(\d{2}:\d{2}:\d{2}[:;]\d{2})')
        
        i = 0
        while i < len(linhas):
            linha = linhas[i].strip()
            match = regex_tc_range.match(linha)
            
            if match:
                # A próxima linha não vazia deve ser o nome
                j = i + 1
                nome_locutor = ""
                while j < len(linhas):
                    potencial_nome = linhas[j].strip()
                    if potencial_nome:
                        nome_locutor = potencial_nome
                        break
                    j += 1
                
                if nome_locutor:
                    # Salva o TC inicial como string para referência simples de ordem
                    mapeamento.append({'tc_str': match.group(1), 'nome': nome_locutor})
                    i = j 
            i += 1
    except: pass
    return mapeamento

def gerar_texto_coutinho():
    print("--- EXTRATOR DE TEXTO SIMPLES (PREMIERE -> COUTINHO) ---")
    
    cwd = os.getcwd()
    f_json = next((f for f in os.listdir(cwd) if f.lower().endswith('.json') and not f.startswith('INPUT') and not f.startswith('Roteiro') and not f.startswith('~$')), None)
    f_txt = next((f for f in os.listdir(cwd) if f.lower().endswith('.txt') and not f.startswith('ROTEIRO') and not f.startswith('~$')), None)
    
    if not f_json:
        print("ERRO: Nenhum JSON de transcrição encontrado.")
        return

    print(f"Lendo JSON: {f_json}")
    try:
        with open(f_json, 'r', encoding='utf-8') as f:
            dados = json.load(f)
    except:
        print("Erro ao ler JSON.")
        return

    # Deep Search para pegar todo o texto
    todos_itens = []
    def deep_search(d):
        if isinstance(d, dict):
            txt = d.get('text') or d.get('content')
            ts = d.get('ts') or d.get('start') or d.get('startTime')
            if txt and ts is not None: 
                todos_itens.append({'text': txt, 'ts': float(ts)})
            for v in d.values(): 
                if isinstance(v, (dict, list)): deep_search(v)
        elif isinstance(d, list):
            for i in d: deep_search(i)
    
    deep_search(dados)
    # Ordena por tempo
    todos_itens.sort(key=lambda x: x['ts'])

    mapa_txt = []
    if f_txt:
        print(f"Lendo Locutores do TXT: {f_txt}")
        mapa_txt = carregar_locutores_txt(f_txt)

    # Gera o arquivo de saída
    with open(ARQUIVO_SAIDA, 'w', encoding='utf-8') as f_out:
        f_out.write("ROTEIRO DE TRANSCRIÇÃO COMPLETO\n")
        f_out.write("===============================\n\n")
        
        buffer_frase = []
        # Aproximação: vamos quebrar parágrafos a cada X segundos de pausa ou a cada Y palavras
        ultimo_ts = 0
        locutor_atual = "Entrevistado"
        idx_locutor = 0
        
        # Fator de conversão (auto-detect simples)
        fator = 1.0
        if todos_itens and todos_itens[-1]['ts'] > 500000: # Se for muito grande, é MS
             fator = 0.001

        for i, item in enumerate(todos_itens):
            ts_sec = item['ts'] * fator
            texto = item['text']
            
            # Tenta atualizar o locutor baseado na "ordem" aproximada do TXT
            # (Lógica simplificada: muda o locutor a cada bloco grande de tempo se o TXT tiver marcas)
            # Para refinar, precisaríamos converter TC string para segundos, mas vamos manter simples:
            # Se o TXT existe, vamos tentar usar os nomes dele sequencialmente se houver match visual?
            # Melhor: Vamos usar "Entrevistado" se não tiver certeza, ou o nome do TXT se ele tiver poucos nomes.
            
            # Lógica de Quebra de Parágrafo (Pausa > 1.5s)
            if buffer_frase and (ts_sec - ultimo_ts > 1.5):
                bloco = " ".join(buffer_frase)
                
                # Tenta pegar nome do TXT proporcionalmente (muito rústico, mas ajuda)
                nome_exibicao = "Entrevistado"
                if mapa_txt and idx_locutor < len(mapa_txt):
                    # Se avançamos X% do texto, pegamos o locutor X% da lista? Não, arriscado.
                    # Vamos usar um nome genérico se não tiver certeza.
                    pass

                f_out.write(f"{bloco}\n\n")
                buffer_frase = []
            
            buffer_frase.append(texto)
            ultimo_ts = ts_sec + 0.5 # Estima fim da palavra

        if buffer_frase:
            f_out.write(" ".join(buffer_frase))

    print(f"\nSUCESSO! Arquivo '{ARQUIVO_SAIDA}' gerado.")
    print("Envie este arquivo para o Coutinho.")

if __name__ == "__main__":
    gerar_texto_coutinho()
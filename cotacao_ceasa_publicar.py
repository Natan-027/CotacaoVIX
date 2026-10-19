"""
Robô de PUBLICAÇÃO diária - CEASA-ES Grande Vitória

Roda várias vezes por dia (a cada 20 min, das 9h às 12h40, de seg. a sex.), pensado para
o GitHub Actions. Em cada rodada:

  1. Fim de semana, ou boletim de hoje já publicado COMPLETO?  -> encerra na hora.
     (completo = ao menos 90% dos produtos do dia anterior; se veio pela metade, consulta de novo)
  2. Abre o site e vê se a data de hoje já está disponível com a tabela de produtos.
     Se ainda não saiu, encerra tranquilo (a próxima rodada tenta de novo).
  3. Se saiu: grava o dia em dados/cotacoes.csv e gera docs/cotacao.html e docs/cotacao.json.

Precisa estar na mesma pasta que cotacao_ceasa.py e cotacao_ceasa_historico.py.

Opções:
  --precisa-rodar     só diz se vale a pena rodar (não abre o navegador)
  --data AAAA-MM-DD   simula "hoje" com outra data (para testes; também vale ignorar fim de semana)
                      (no GitHub, o mesmo vale pelo campo "data" ao rodar manualmente)
"""

import csv
import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRASILIA = timezone(timedelta(hours=-3))   # o Brasil não usa horário de verão
CSV_ARQUIVO = Path("dados/cotacoes.csv")
SAIDA = Path("docs")
CABECALHO = ["Dia", "Mês", "Ano", "Produto", "M.C."]
MINIMO_PRODUTOS = int(os.environ.get("MINIMO_PRODUTOS", "20"))  # menos que isso = tabela incompleta
FRACAO_COMPLETO = 0.9   # boletim completo = ao menos 90% dos produtos do dia anterior


def argumento(nome):
    if nome in sys.argv:
        return sys.argv[sys.argv.index(nome) + 1]
    return None


def data_alvo():
    """Devolve (data, explicita). Explícita = veio de --data / DATA_TESTE (teste manual)."""
    texto = argumento("--data") or os.environ.get("DATA_TESTE", "").strip()
    if texto:
        return datetime.strptime(texto, "%Y-%m-%d").date(), True
    return datetime.now(BRASILIA).date(), False


# ------------------------------------------------------- verificações leves ----
def contagens():
    """Quantos produtos cada dia tem no CSV: {(dia, mês, ano): quantidade}, na ordem do arquivo."""
    cont = {}
    if CSV_ARQUIVO.exists():
        with CSV_ARQUIVO.open(encoding="utf-8-sig", newline="") as f:
            for linha in csv.reader(f, delimiter=";"):
                if len(linha) >= 3 and linha[0].isdigit():
                    chave = tuple(linha[:3])
                    cont[chave] = cont.get(chave, 0) + 1
    return cont


def chave(dia):
    return (str(dia.day), str(dia.month), str(dia.year))


def esperado(dia):
    """Quantos produtos um boletim completo deve ter: 90% do dia anterior publicado (mínimo MINIMO_PRODUTOS).
    O CEASA lança o boletim aos poucos de manhã; com menos que isso, o dia ainda está incompleto."""
    outros = [n for k, n in contagens().items() if k != chave(dia)]
    if not outros:
        return MINIMO_PRODUTOS
    return max(MINIMO_PRODUTOS, int(outros[-1] * FRACAO_COMPLETO))


def publicados(dia):
    return contagens().get(chave(dia), 0)


def precisa_rodar(dia, explicita):
    if not explicita and dia.weekday() >= 5:
        return False, f"{dia:%d/%m/%Y} é fim de semana: nada a fazer."
    n, meta = publicados(dia), esperado(dia)
    if n >= meta:
        return False, f"O boletim de {dia:%d/%m/%Y} já foi publicado completo ({n} produtos): nada a fazer."
    if n:
        return True, (f"O boletim de {dia:%d/%m/%Y} foi publicado incompleto ({n} produtos, "
                      f"esperado ao menos {meta}): vou consultar de novo.")
    return True, f"Boletim de {dia:%d/%m/%Y} ainda não publicado: vou consultar o site."


def avisar_github(rodar):
    """Passa o resultado para os próximos passos do workflow (só existe no GitHub Actions)."""
    destino = os.environ.get("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(f"rodar={'true' if rodar else 'false'}\n")


# ------------------------------------------------------------- publicação ----
def preco_br(valor):
    return f"{valor:.2f}".replace(".", ",")


def preco_ou_traco(valor):
    """Preço no formato 4,55; traço quando o boletim não trouxe o valor."""
    try:
        if valor is None or valor != valor:   # vazio ou NaN
            return "–"
        return preco_br(float(valor))
    except (TypeError, ValueError):
        return "–"


def gravar_csv(dia, itens):
    """Grava o dia no CSV (separador ';' e vírgula decimal: abre direto no Excel em português).
    Se o dia já existia (boletim incompleto), as linhas antigas dele são substituídas no mesmo lugar."""
    CSV_ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    novas = [[str(dia.day), str(dia.month), str(dia.year), it["produto"], preco_br(it["preco"])]
             for it in itens]
    linhas = [CABECALHO]
    if CSV_ARQUIVO.exists():
        with CSV_ARQUIVO.open(encoding="utf-8-sig", newline="") as f:
            linhas = [l for l in csv.reader(f, delimiter=";") if l]
    pos = next((i for i, l in enumerate(linhas) if tuple(l[:3]) == chave(dia)), None)
    linhas = [l for l in linhas if tuple(l[:3]) != chave(dia)]
    if pos is None:
        linhas += novas
    else:
        linhas[pos:pos] = novas
    with CSV_ARQUIVO.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";").writerows(linhas)


def data_da_pagina():
    arquivo = SAIDA / "cotacao.json"
    try:
        return datetime.fromisoformat(json.loads(arquivo.read_text(encoding="utf-8"))["data"]).date()
    except Exception:  # noqa: BLE001
        return None


PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cotação CEASA-ES</title>
<style>
  :root {{ --texto:#1f2a24; --suave:#66736b; --linha:#e3e8e5; --destaque:#1b6b3a; --fundo-cab:#f3f7f4;
          --fundo-par:#eaf5ee; --borda:18px; --meio:4px; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:12px; font:15px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         color:var(--texto); background:transparent; }}
  .cartao {{ background:#fff; border:1px solid var(--linha); border-radius:12px; overflow:hidden; max-width:760px; margin:0 auto; }}
  header {{ padding:16px 18px 12px; border-bottom:1px solid var(--linha); }}
  .origem {{ margin:0; font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:var(--suave); }}
  h1 {{ margin:2px 0 0; font-size:20px; color:var(--destaque); }}
  .nota {{ margin:2px 0 0; font-size:13px; color:var(--suave); }}
  .busca {{ padding:10px 18px; border-bottom:1px solid var(--linha); display:flex; gap:10px; align-items:center; }}
  .busca input {{ flex:1; min-width:0; padding:8px 10px; border:1px solid var(--linha); border-radius:8px; font:inherit; }}
  .busca span {{ color:var(--suave); font-size:13px; white-space:nowrap; }}
  .rolagem {{ max-height:560px; overflow:auto; }}
  table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
  /* larguras em %, para nunca precisar de rolagem lateral no celular; a embalagem fica embaixo do nome */
  col.c1 {{ width:43%; }}
  col.c2, col.c3, col.c4 {{ width:19%; }}
  th, td {{ padding:4px var(--meio); text-align:left; border-bottom:1px solid var(--linha); overflow-wrap:break-word; }}
  th:first-child, td:first-child {{ padding-left:var(--borda); }}
  th:last-child, td:last-child {{ padding-right:var(--borda); }}
  th {{ position:sticky; top:0; background:var(--fundo-cab); font-size:12px; text-transform:uppercase;
       letter-spacing:.04em; color:var(--suave); padding-top:6px; padding-bottom:6px; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  th.num {{ text-align:right; }}
  td .emb {{ display:block; color:var(--suave); font-size:12px; }}
  td.mc {{ font-weight:600; }}
  tr.par td {{ background:var(--fundo-par); }}
  tr:last-child td {{ border-bottom:0; }}
  footer {{ padding:10px 18px; font-size:12px; color:var(--suave); border-top:1px solid var(--linha); }}
  @media (max-width:520px) {{ :root {{ --borda:10px; }} header, .busca, footer {{ padding-left:10px; padding-right:10px; }} }}
</style>
</head>
<body>
<div class="cartao">
  <header>
    <p class="origem">CEASA-ES · Grande Vitória</p>
    <h1>Cotação do dia {data_br}</h1>
    <p class="nota">Preços em R$: mínimo, comum e máximo.</p>
  </header>
  <div class="busca">
    <input id="q" type="search" placeholder="Buscar produto..." aria-label="Buscar produto">
    <span id="contagem">{total} produtos</span>
  </div>
  <div class="rolagem">
    <table>
      <colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"></colgroup>
      <thead><tr><th>Produto</th><th class="num">Mín</th><th class="num">Comum</th><th class="num">Máx</th></tr></thead>
      <tbody id="corpo">
{linhas}
      </tbody>
    </table>
  </div>
  <footer>Informações atualizadas em {atualizado} conforme o boletim diário do CEASA-ES.{aviso}</footer>
</div>
<script>
  var q = document.getElementById('q'), linhas = document.querySelectorAll('#corpo tr'),
      contagem = document.getElementById('contagem');
  q.addEventListener('input', function () {{
    var t = q.value.trim().toLowerCase(), n = 0;
    linhas.forEach(function (tr) {{
      var ok = tr.textContent.toLowerCase().indexOf(t) !== -1;
      tr.style.display = ok ? '' : 'none';
      if (ok) {{ tr.classList.toggle('par', n % 2 === 1); n++; }}
    }});
    contagem.textContent = n + (n === 1 ? ' produto' : ' produtos');
  }});
</script>
</body>
</html>
"""


def gerar_pagina(dia, itens, atualizado_em=None, escrever_json=True, completo=True):
    SAIDA.mkdir(parents=True, exist_ok=True)
    agora = atualizado_em or datetime.now(BRASILIA)
    linhas = "\n".join(
        f'        <tr{" class=\"par\"" if i % 2 else ""}><td>{html.escape(it["produto"])}'
        f'<span class="emb">{html.escape(it["embalagem"])}</span></td>'
        f'<td class="num">{preco_ou_traco(it.get("minimo"))}</td>'
        f'<td class="num mc">{preco_br(it["preco"])}</td>'
        f'<td class="num">{preco_ou_traco(it.get("maximo"))}</td></tr>'
        for i, it in enumerate(itens))
    (SAIDA / "cotacao.html").write_text(
        PAGINA.format(data_br=f"{dia:%d/%m/%Y}", total=len(itens), linhas=linhas,
                      atualizado=f"{agora:%d/%m/%Y às %H:%M}",
                      aviso="" if completo else " O CEASA ainda está lançando o boletim de hoje: "
                                                 "a lista será completada nas próximas atualizações."),
        encoding="utf-8")
    if escrever_json:
        (SAIDA / "cotacao.json").write_text(
            json.dumps({"data": dia.isoformat(), "data_br": f"{dia:%d/%m/%Y}",
                        "mercado": "CEASA Grande Vitória",
                        "atualizado_em": agora.isoformat(timespec="seconds"),
                        "completo": completo,
                        "itens": itens}, ensure_ascii=False, indent=1),
            encoding="utf-8")


def modo_refazer():
    """--data refazer (ou DATA_TESTE=refazer): só reconstrói a página com os dados já publicados."""
    texto = (argumento("--data") or os.environ.get("DATA_TESTE", "")).strip().lower()
    return texto == "refazer"


def refazer_pagina():
    arquivo = SAIDA / "cotacao.json"
    if not arquivo.exists():
        print("Ainda não há boletim publicado: nada para refazer.")
        return 0
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    dia = datetime.fromisoformat(dados["data"]).date()
    atualizado = datetime.fromisoformat(dados["atualizado_em"])
    gerar_pagina(dia, dados["itens"], atualizado, escrever_json=False,
                 completo=dados.get("completo", True))
    print(f"Página refeita com os dados de {dia:%d/%m/%Y} ({len(dados['itens'])} produtos), "
          "sem consultar o site.")
    return 0


# ------------------------------------------------------------ diagnóstico ----
EVENTOS = []   # diálogos, erros de JavaScript e pedidos que falharam durante a consulta


def observar(page):
    page.on("dialog", lambda d: (EVENTOS.append(f"diálogo: {d.message[:120]}"), d.accept()))
    page.on("pageerror", lambda e: EVENTOS.append(f"erro JS: {str(e)[:150]}"))
    page.on("requestfailed", lambda r: EVENTOS.append(f"pedido falhou: {r.url[:100]}"))


def diagnosticar(pagina):
    """Quando a tabela não aparece, guarda o que o robô viu em docs/debug/ e mostra um resumo."""
    try:
        try:
            estado = pagina.evaluate(
                "typeof Nm_Proc_Atualiz === 'undefined' ? 'indefinido' : String(Nm_Proc_Atualiz)")
        except Exception:  # noqa: BLE001
            estado = "?"
        print(f"Diagnóstico: Nm_Proc_Atualiz={estado} | eventos da página: {EVENTOS[-8:] or 'nenhum'}")
        pasta = SAIDA / "debug"
        pasta.mkdir(parents=True, exist_ok=True)
        texto = " ".join(pagina.inner_text("body").split())
        print(f"Diagnóstico: endereço {pagina.url} | título {pagina.title()!r} "
              f"| frames {len(pagina.frames)}")
        print(f"Diagnóstico: texto visível ({len(texto)} caracteres): {texto[:300] or '(vazio)'}")
        (pasta / "resultado.html").write_text(pagina.content(), encoding="utf-8")
        pagina.screenshot(path=str(pasta / "resultado.png"), full_page=True)
    except Exception as e:  # noqa: BLE001
        print(f"Diagnóstico: não consegui inspecionar a página ({e})")


# ------------------------------------------------------------- principal ----
def main():
    if modo_refazer():
        if "--precisa-rodar" in sys.argv:
            print("Modo refazer: vou reconstruir a página sem consultar o site.")
            avisar_github(True)
            return 0
        return refazer_pagina()

    dia, explicita = data_alvo()
    rodar, motivo = precisa_rodar(dia, explicita)
    print(motivo)

    if "--precisa-rodar" in sys.argv:
        avisar_github(rodar)
        return 0
    if not rodar:
        return 0

    # imports pesados só aqui, para a verificação acima funcionar sem nada instalado
    from playwright.sync_api import sync_playwright
    import cotacao_ceasa as cot
    import cotacao_ceasa_historico as hist

    if os.environ.get("CEASA_URL"):
        cot.URL = os.environ["CEASA_URL"]
    hist.ESPERA_TABELA = 25        # o servidor é lento visto de fora do Brasil: espera até ~25 s pela tabela
    hist.AO_FALHAR = diagnosticar

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            observar(page)
            datas = hist.listar_datas(page)
            valor = next((v for d, v in datas if d.date() == dia), None)
            if valor is None:
                browser.close()
                print(f"Ainda não saiu: {dia:%d/%m/%Y} não consta na lista de datas do site.")
                return 0
            tabela = hist.consultar_dia(page, valor)
            browser.close()
    except Exception as e:  # noqa: BLE001
        print(f"ERRO ao acessar o site do CEASA: {e}")
        return 1

    if tabela is None or "M.C." not in tabela.columns or len(tabela) < MINIMO_PRODUTOS:
        n = 0 if tabela is None else len(tabela)
        print(f"Ainda incompleto: a tabela de {dia:%d/%m/%Y} veio com {n} produtos "
              f"(mínimo esperado: {MINIMO_PRODUTOS}). Tento de novo na próxima rodada.")
        return 0

    tabela = tabela.dropna(subset=["M.C."])
    if cot.PRODUTOS:
        tabela = tabela[tabela["Produto"].isin(cot.PRODUTOS)]
    def numero(v):
        try:
            v = float(v)
            return None if v != v else v
        except (TypeError, ValueError):
            return None

    vazio = [None] * len(tabela)
    itens = [{"produto": str(p), "embalagem": "" if e is None or str(e) == "<NA>" else str(e),
              "minimo": numero(mn), "preco": float(mc), "maximo": numero(mx)}
             for p, e, mn, mc, mx in zip(tabela["Produto"],
                                         tabela.get("Embalagem", [""] * len(tabela)),
                                         tabela.get("Mínimo", vazio), tabela["M.C."],
                                         tabela.get("Máximo", vazio))]
    if not itens:
        print("Nenhum produto para publicar (confira a lista PRODUTOS).")
        return 0

    antes, meta = publicados(dia), esperado(dia)
    if len(itens) <= antes:
        print(f"O site ainda mostra {len(itens)} produtos para {dia:%d/%m/%Y}, e já publiquei {antes}: "
              "nada mudou. Tento de novo na próxima rodada.")
        return 0

    completo = len(itens) >= meta
    gravar_csv(dia, itens)
    pagina = data_da_pagina()
    if pagina is None or dia >= pagina:     # não troca a página de um dia mais novo por um dia antigo
        gerar_pagina(dia, itens, completo=completo)
    situacao = "completo" if completo else f"ainda incompleto (esperado ao menos {meta})"
    print(f"Publicado: {len(itens)} produtos de {dia:%d/%m/%Y} ({situacao}) "
          f"em {CSV_ARQUIVO} e {SAIDA / 'cotacao.html'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Envia o PDF da fatura direto à API da Anthropic (sem OCR e sem OpenRouter) e registra a chamada:
    outputs/rendered-prompts/prompt-<n>.md   prompt exatamente como enviado (+ nome do PDF)
    outputs/results/result-<n>.json          lista [{id, categoria, duvida}] (formato do Kanban)
    outputs/extract-pdf-<n>.json             lançamentos extraídos pelo modelo (formato do Kanban)
O número <n> é o mesmo nas três saídas (reserva feita por reserve_run, neste arquivo).

Uso:
    python ask_pdf.py "input/Latampass Itau.pdf"
    python ask_pdf.py "input/Latampass Itau.pdf" -f prompt-pdf.md -m claude-sonnet-5-5
    python ask_pdf.py "input/Latampass Itau.pdf" -p SENHA          # PDF criptografado
    python ask_pdf.py "input/Latampass Itau.pdf" --dry-run         # só monta e salva o prompt

Requer ANTHROPIC_API_KEY no ambiente ou em um arquivo .env.
"""
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

import anthropic
import pymupdf
from dotenv import load_dotenv

PROMPT_PDF = Path(__file__).resolve().parent / "prompt-pdf.md"
PROMPTS_DIR = Path("outputs/rendered-prompts")
RESULTS_DIR = Path("outputs/results")

DEFAULT_MODEL = "claude-sonnet-5-5"


def carregar_categorias(path: Path = PROMPT_PDF) -> list[str]:
    """Lê a lista de categorias da linha `categoria` da seção 3 de prompt-pdf.md (fonte única)."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^- `categoria`: exatamente um destes valores: (.+?)\.?\s*$", text, re.M)
    if not m:
        sys.exit(f"Erro: linha de categorias não encontrada em {path}")
    return [c.strip() for c in m[1].split(",") if c.strip()]


CATEGORIAS = carregar_categorias()
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["total_lanc_atuais", "lancamentos"],
    "properties": {
        "total_lanc_atuais": {"type": "number"},
        "lancamentos": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "secao", "data", "descricao", "valor", "categoria", "duvida"],
            "properties": {
                "id": {"type": "integer"},
                "secao": {"type": "string", "enum": ["compras", "internacional", "produtos"]},
                "data": {"type": "string"},
                "descricao": {"type": "string"},
                "valor": {"type": "number"},
                "categoria": {"type": "string", "enum": CATEGORIAS},
                "duvida": {"type": "boolean"},
            },
        }},
    },
}


def reserve_run(prompt: str, ext: str = "md") -> tuple[Path, Path]:
    """Reserva o próximo número n e grava prompt-<n>.md e result-<n>.<ext> (em branco)."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    nums = [
        int(m[1])
        for d, pre in ((PROMPTS_DIR, "prompt"), (RESULTS_DIR, "result"))
        for f in d.glob(f"{pre}-*.*")
        if (m := re.fullmatch(rf"{pre}-(\d+)\.(?:md|json)", f.name))
    ]
    n = max(nums, default=0) + 1
    while True:
        result_path = RESULTS_DIR / f"result-{n}.{ext}"
        prompt_path = PROMPTS_DIR / f"prompt-{n}.md"
        try:
            # "x": nunca sobrescreve; criar o result primeiro reserva o número.
            result_path.touch(exist_ok=False)
        except FileExistsError:
            n += 1
            continue
        try:
            with open(prompt_path, "x", encoding="utf-8") as f:
                f.write(prompt)
        except FileExistsError:  # prompt órfão com esse número: pula para o próximo
            result_path.unlink()
            n += 1
            continue
        return prompt_path, result_path


def preparar_pdf(path: str, senha: str | None) -> bytes:
    """Devolve os bytes do PDF; se estiver criptografado, autentica e devolve a versão sem senha."""
    data = Path(path).read_bytes()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        sys.exit(f"Erro ao abrir PDF: {e}")
    if not doc.is_encrypted:
        return data
    if not senha:
        sys.exit("Erro: o PDF está criptografado; informe a senha com -p SENHA.")
    if not doc.authenticate(senha):
        sys.exit("Erro: senha incorreta para o PDF.")
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)


def validar(lancs: list, total: float) -> None:
    """Confere ids, categorias, estornos e soma contra o total impresso na fatura (stderr)."""
    ids = [l["id"] for l in lancs]
    seq = set(range(1, len(ids) + 1))
    dup = sorted({i for i in ids if ids.count(i) > 1})
    falta = sorted(seq - set(ids))
    fora = sorted(set(ids) - seq)
    for nome, lst in (("duplicados", dup), ("ausentes na sequência 1..N", falta),
                      ("fora da sequência 1..N", fora)):
        if lst:
            print(f"ATENÇÃO: ids {nome}: {lst}", file=sys.stderr)
    inval = [l["id"] for l in lancs if l["categoria"] not in CATEGORIAS]
    if inval:
        print(f"ATENÇÃO: categorias inválidas: ids {inval}", file=sys.stderr)
    errs = [l["id"] for l in lancs if l["valor"] < 0 and l["categoria"] != "OUTROS"]
    if errs:
        print(f"ATENÇÃO: estornos fora de OUTROS: ids {errs}", file=sys.stderr)

    sub: dict[str, float] = {}
    for l in lancs:
        sub[l["categoria"]] = sub.get(l["categoria"], 0) + l["valor"]
    print("\nSubtotais (líquidos de estornos):", file=sys.stderr)
    for k, v in sorted(sub.items()):
        print(f"  {k}: R$ {v:,.2f}", file=sys.stderr)
    soma = round(sum(l["valor"] for l in lancs), 2)
    status = "ok" if round(soma * 100) == round(total * 100) else "DIVERGENTE"
    print(f"  soma = {soma:,.2f} vs 'Total dos lançamentos atuais' {total:,.2f}: {status}", file=sys.stderr)
    duv = [l["id"] for l in lancs if l["duvida"]]
    print(f"  Itens com dúvida: {len(duv)} (ids {duv})", file=sys.stderr)


def processar(text: str, pdf_name: str, result_path: Path, extract_path: Path) -> list:
    """Grava result (lista de classificações) e extract-pdf (formato do Kanban); valida e devolve a lista."""
    try:
        data = json.loads(text)
        lancs = data["lancamentos"]
        total = data["total_lanc_atuais"]
        items = [{"id": l["id"], "categoria": l["categoria"], "duvida": l["duvida"]} for l in lancs]
        extract = {
            "arquivo": pdf_name,
            "origem": "pdf-anthropic",
            "campos_resumo": {"total_lanc_atuais": total},
            "lancamentos": [
                {"id": l["id"], "pagina": 0, "secao": l["secao"], "data": l["data"],
                 "descricao": l["descricao"], "valor": l["valor"], "extra": ""}
                for l in lancs
            ],
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        result_path.write_text(text, encoding="utf-8")  # guarda a resposta crua para inspeção
        sys.exit(f"Erro: resposta fora do schema ({e}); bruto salvo em {result_path}")

    result_path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    extract_path.write_text(json.dumps(extract, ensure_ascii=False, indent=1), encoding="utf-8")
    validar(lancs, total)
    return items


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Envia o PDF da fatura à API da Anthropic.")
    parser.add_argument("pdf", help="caminho do PDF da fatura")
    parser.add_argument("-f", "--file", default="prompt-pdf.md", help="prompt (padrão: prompt-pdf.md)")
    parser.add_argument("-m", "--model", default=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL))
    parser.add_argument("-p", "--password", metavar="SENHA", help="senha do PDF, se estiver criptografado")
    parser.add_argument("--dry-run", action="store_true",
                        help="só monta e salva o prompt (result em branco); não chama a API")
    args = parser.parse_args()

    if not args.dry_run and not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("Erro: defina ANTHROPIC_API_KEY (ambiente ou .env).")
    if not os.path.isfile(args.pdf):
        sys.exit(f"Erro: PDF não encontrado: {args.pdf}")
    try:
        prompt = Path(args.file).read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"Erro ao ler prompt: {e}")
    pdf_name = Path(args.pdf).name
    pdf_bytes = preparar_pdf(args.pdf, args.password)

    saved_prompt = prompt + f"\n\n<!-- anexo: {pdf_name} -->\n"
    prompt_path, result_path = reserve_run(saved_prompt, "json")
    if args.dry_run:
        print(f"Dry-run: prompt salvo em {prompt_path} ({len(prompt)} caracteres)")
        print(f"Result em branco criado em {result_path}")
        return

    n = result_path.stem.removeprefix("result-")
    extract_path = RESULTS_DIR.parent / f"extract-pdf-{n}.json"

    def abort(msg):  # não deixa par prompt/result órfão de uma chamada que falhou
        prompt_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)
        sys.exit(msg)

    client = anthropic.Anthropic(timeout=600)
    try:
        with client.messages.stream(
            model=args.model,
            max_tokens=64000,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                }},
                {"type": "text", "text": prompt},
            ]}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        ) as stream:
            resp = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        abort(f"Erro de autenticação: verifique ANTHROPIC_API_KEY ({e.message})")
    except anthropic.RateLimitError as e:
        abort(f"Limite de requisições atingido: {e.message}")
    except anthropic.BadRequestError as e:
        abort(f"Requisição inválida: {e.message}")
    except anthropic.APIStatusError as e:
        abort(f"Erro da API ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError as e:
        abort(f"Erro de conexão com a API: {e}")

    if resp.stop_reason == "max_tokens":
        abort("Erro: resposta truncada (max_tokens); nada foi gravado.")
    if resp.stop_reason == "refusal":
        abort(f"Erro: o modelo recusou a requisição: {resp.stop_details}")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if text is None:
        abort("Erro: resposta sem bloco de texto.")

    items = processar(text, pdf_name, result_path, extract_path)
    print(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"\nPrompt: {prompt_path}\nResult: {result_path}\nExtract: {extract_path}", file=sys.stderr)
    print(f"Kanban: python kanban/serve.py -r {result_path} -e {extract_path}", file=sys.stderr)
    print(f"        python kanban/build_standalone.py -r {result_path} -e {extract_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

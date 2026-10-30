import html
import os
HERE=os.path.dirname(os.path.abspath(__file__))
cats = ["FORNECEDOR","OPERACIONAL","MARKETING/COMERCIAL","INVESTIMENTO","DESPESA ADMINISTRATIVA","FOLHA DE PAGAMENTO","CUSTO DO CARRO","DESPESAS FINANCEIRAS","PESSOA FISICA","OUTROS"]
# dados fictícios
cards = {
 0:[("Distribuidora Exemplo Ltda","1.250,00",False,""),("Papelaria Fictícia","89,90",False,"changed"),("Atacado Modelo SA","432,10",False,"")],
 1:[("Hospedagem Servidor Demo","199,00",False,""),("Software Gestão Teste","349,00",True,"")],
 2:[("Anúncios Online Exemplo","500,00",False,""),("Gráfica Imaginária","210,00",False,"")],
 3:[("Notebook Loja Fictícia","4.899,00",False,"")],
 4:[("Contabilidade Exemplo","650,00",False,""),("Correios Demo","32,40",False,"")],
 5:[("Pró-labore Fictício","3.000,00",False,"")],
 6:[("Posto Combustível Teste","280,00",False,""),("Estacionamento Demo","25,00",False,"")],
 7:[("Tarifa Bancária Exemplo","19,90",False,""),("IOF Compra Exterior","12,35",False,"")],
 8:[],
 9:[("Estorno Loja Exemplo","-120,00",False,"neg"),("Compra Não Identificada","77,70",True,"")],
}
totals=[1772.0,548.0,710.0,4899.0,682.4,3000.0,305.0,32.25,0,-42.3]
def card(d,v,doubt,tag):
    cls="card doubt" if doubt else "card"
    vcls="valor neg" if tag=="neg" else "valor"
    meta='<span>05/09</span>'
    if tag=="changed": meta+='<span class="tag changed">alterado</span>'
    if doubt: meta+='<span class="tag review">dúvida</span><span class="acts"><button class="mini">Aceitar</button><button class="mini">Mover…</button></span>'
    return f'<div class="{cls}"><div class="card-main"><span class="desc">{html.escape(d)}</span><span class="{vcls}">R$ {v}</span></div><div class="card-meta">{meta}</div></div>'
lanes=""
for i,c in enumerate(cats):
    h=i*36
    cs=cards[i]
    body="".join(card(*x) for x in cs) or '<div class="lane-empty">Arraste lançamentos para cá</div>'
    pend=sum(1 for x in cs if x[2])
    p=f'<span class="pend">{pend} dúvida</span>' if pend else ""
    tot=f"R$ {totals[i]:,.2f}".replace(",","X").replace(".",",").replace("X",".")
    lanes+=f'<section class="lane{" empty" if not cs else ""}" style="--h:{h}"><div class="lane-head"><div class="lane-title"><span>{c}</span><span class="count">{len(cs)}</span></div><div class="lane-meta"><span>{tot}</span>{p}</div></div><div class="cards">{body}</div></section>'
pos=[t for t in totals if t>0]; s=sum(pos)
bars="".join(f'<div style="flex:{t/s:.4f};background:hsl({i*36} 40% 42%)"></div>' for i,t in enumerate(totals) if t>0)
legend="".join(f'<span class="lg"><i style="background:hsl({i*36} 40% 42%)"></i>{cats[i]}</span>' for i,t in enumerate(totals) if t>0)
tpl=open(os.path.join(HERE,"v1-template.html")).read()
open(os.path.join(HERE,"v1.html"),"w").write(tpl.replace("{{LANES}}",lanes).replace("{{BARS}}",bars).replace("{{LEGEND}}",legend))

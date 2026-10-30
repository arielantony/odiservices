import html
import os
HERE=os.path.dirname(os.path.abspath(__file__))
C=[("Fornecedor","#2B4C9B"),("Operacional","#3E8A74"),("Marketing/comercial","#EE5E27"),("Investimento","#6A55A8"),("Despesa administrativa","#8F7B3C"),("Folha de pagamento","#2C8A9A"),("Custo do carro","#B04A6A"),("Despesas financeiras","#56657A"),("Pessoa física","#9C6B3F"),("Outros","#8B8F98")]
cards={0:[("Distribuidora Exemplo Ltda",1250.0,0,""),("Papelaria Fictícia",89.9,0,"Movido por você"),("Atacado Modelo SA",432.1,0,"")],
1:[("Hospedagem Servidor Demo",199.0,0,""),("Software Gestão Teste",349.0,1,"")],
2:[("Anúncios Online Exemplo",500.0,0,""),("Gráfica Imaginária",210.0,0,"")],
3:[("Notebook Loja Fictícia",4899.0,0,"")],
4:[("Contabilidade Exemplo",650.0,0,""),("Correios Demo",32.4,0,"")],
5:[("Pró-labore Fictício",3000.0,0,"")],
6:[("Posto Combustível Teste",280.0,0,""),("Estacionamento Demo",25.0,0,"")],
7:[("Tarifa Bancária Exemplo",19.9,0,""),("IOF Compra Exterior",12.35,0,"")],
8:[],9:[("Estorno Loja Exemplo",-120.0,0,""),("Compra Não Identificada",77.7,1,"")]}
def brl(v): return ("R$ "+f"{v:,.2f}".replace(",","X").replace(".",",").replace("X",".")).replace("R$ -","−R$ ")
tot=[sum(c[1] for c in cards[i]) for i in range(10)]
def card(d,v,doubt,note,color):
    cls="card doubt" if doubt else "card"
    foot=""
    if doubt: foot='<div class="cfoot"><span class="mini">Confirmar</span><span class="mini">Mover</span></div>'
    elif note: foot=f'<div class="cfoot"><span class="note">{note}</span></div>'
    neg=" neg" if v<0 else ""
    return f'<div class="{cls}"><span class="d">{html.escape(d)}</span><span class="v{neg}">{brl(v)}</span><span class="dt">05 set</span>{foot}</div>'
lanes=""
for i,(n,col) in enumerate(C):
    cs=cards[i]; pend=sum(c[2] for c in cs)
    body="".join(card(*c,col) for c in cs) or '<div class="lempty">Nenhum lançamento aqui. Arraste um cartão para esta categoria.</div>'
    p=f'<span class="pend">{pend} para revisar</span>' if pend else ""
    lanes+=f'<section class="lane{" isempty" if not cs else ""}"><header class="lh"><i style="background:{col}"></i><span class="ln">{n}</span><span class="lc">{len(cs)}</span></header><div class="lsum">{brl(tot[i])} {p}</div><div class="lcards">{body}</div></section>'
pos=[(i,t) for i,t in enumerate(tot) if t>0]; s=sum(t for _,t in pos)
bars="".join(f'<span style="flex:{t/s:.4f};background:{C[i][1]}"></span>' for i,t in pos)
top3=sorted(pos,key=lambda x:-x[1])[:3]
leg="".join(f'<li><i style="background:{C[i][1]}"></i>{C[i][0]}<b>{t/s*100:.0f}%</b></li>' for i,t in top3)
t=open(os.path.join(HERE,"v3-template.html")).read()
open(os.path.join(HERE,"v3.html"),"w").write(t.replace("{{LANES}}",lanes).replace("{{BARS}}",bars).replace("{{LEG}}",leg).replace("{{TOTAL}}",brl(sum(tot))))

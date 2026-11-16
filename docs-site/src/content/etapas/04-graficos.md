---
titulo: Gráficos e mapa
resumo: Uma fundação única para todo gráfico, leitura sem HTML, chips de canal, cor nunca como única pista e o cursor 20× mais rápido.
ordem: 4
status: concluida
risco: medio
arquivos:
  - lmu_telemetry/presentation/plotting.py
  - lmu_telemetry/presentation/chart_widgets.py
  - lmu_telemetry/presentation/chart_panel.py
  - lmu_telemetry/presentation/track_map.py
  - lmu_telemetry/presentation/gg_panel.py
  - lmu_telemetry/presentation/consistency_panel.py
  - lmu_telemetry/presentation/theme.py
  - scripts/bench_charts.py
  - tests/test_charts.py
---

## Escopo

`ChartStack` empilha traçados num eixo X compartilhado; `TrackMap` e `FrictionPanel` usam pyqtgraph com proporção igual.

## Referência: "UI Libraries for Claude Code (Ban the AI Look)"

A base pedida foi o vídeo de Griffin Wooldridge ([YouTube](https://www.youtube.com/watch?v=zsCGS-Yzjnw)), que trata de bibliotecas de UI **web** (shadcn, Radix, Sonner, cmdk, NumberFlow, Magic UI). O vídeo não pôde ser assistido daqui; o que se usou foi o resumo do próprio autor ([blog](https://griffinwooldridge.com/blog/best-react-ui-component-libraries)) e uma matéria sobre o vídeo ([Geeky Gadgets](https://www.geeky-gadgets.com/claude-code-ui-libraries/)). As bibliotecas não se aplicam a um app PySide6, mas os princípios sim, e foram traduzidos assim:

| Princípio do vídeo | Aqui |
| --- | --- |
| Use uma *fundação* para o comportamento difícil, não construa do zero | `plotting.make_plot`: um único ponto onde todo gráfico é criado e estilizado. Antes, cada painel configurava o pyqtgraph à mão. |
| O "visual de IA" é o estilo padrão sem retoque | O pyqtgraph de fábrica (eixos claros, fonte padrão, marcas de tick) foi reestilizado pelo tema: linha do eixo na cor de borda, números esmaecidos, sem marcas de tick e com a fonte da escala tipográfica. |
| Componentes *especialistas* para os detalhes | A legenda e o readout deixaram de ser HTML: `LineKey` desenha a linha como ela está no gráfico, e `ReadoutCell` mantém a largura enquanto o número muda (a lição do NumberFlow, sem animação, que atrapalharia a leitura). |
| Um destaque por tela | O Δt continua sendo o único lugar com preenchimento. Nada novo ganhou brilho, sombra ou gradiente. |
| Lista de proibições | Nenhum gradiente atrás de texto, glow, blur, sombra em caixa ou emoji. O antialiasing segue desligado. |

## Tarefas

1. ~~Aplicar os tokens a eixos, grades, legendas e leitura do cursor~~ **Feito (16/11/2026).** Todo gráfico (traçados, mapa, g-g e consistência) sai de `plotting.make_plot`.
2. ~~Trocar o HTML do readout por componente estilizado pelo tema~~ **Feito.** Há uma célula por grandeza, com legenda e valor, e a comparação vem em itálico. A cor do valor vem de uma propriedade `series` que o QSS do tema pinta. `theme.rich` foi removido: nenhum painel monta HTML.
3. ~~Revisar a seleção de canais~~ **Feito.** Os chips acima dos gráficos (Velocidade, Pedais, Volante, Marcha, Rotação, Δt) são as mesmas ações do menu Exibir ▸ Canais: ligar um liga o outro, e um canal sem dados fica cinza nos dois.
4. ~~Rever o rótulo e a unidade de cada eixo~~ **Feito.** "Motor (rpm)" passou a "Rotação (rpm)" e "Delta-t (s)" a "Δt (s)", e cada célula do readout leva a unidade ("Velocidade · km/h"). A legenda diz só qual linha é qual volta ("Volta 5", "Ref. · volta 3"), porque tempo e diferença já estão no cabeçalho; o texto completo fica na dica.
5. ~~Medir o tempo de redesenho antes e depois~~ **Feito.** `scripts/bench_charts.py`, com uma volta de Le Mans (13 600 m), seis linhas, duas voltas e Δt, rodado no mesmo script antes e depois:

| Operação | Antes | Depois |
| --- | --- | --- |
| Mover o cursor | 86 ms | **4 ms** |
| Repintura completa | 95 ms | 3 ms |
| Arrastar (pan) | 115 ms | 38 ms |
| Abrir a volta | 120 ms | 88 ms |

O cursor custava cinco quadros por movimento. Três causas, todas guardadas por teste:

- **Cache das camadas estáticas.** Curvas e eixos ganharam `DeviceCoordinateCache`, então mover o cursor copia pixels já desenhados em vez de redesenhar milhares de pontos.
- **Limite do `QPixmapCache`.** O padrão do Qt é 10 MB, e com seis linhas cada uma despejava o cache da anterior. Com o cache ligado e esse limite, o cursor chegou a 120 ms, pior que sem cache. O limite agora acompanha o tamanho da tela (64 a 256 MB, como teto).
- **Faixa Y fixa por volta.** O auto-range do pyqtgraph reaplicava a faixa a cada pintura e descartava o cache. O resultado na tela é o mesmo, porque o Y nunca é arrastado.

No caminho apareceu um defeito antigo: os pens criados fora do `pg.mkPen` não eram *cosméticos*, então a espessura era medida em unidades dos dados (2,4 m num mapa de 1,2 km, menos de um pixel). Agora toda espessura é em pixels.

## Critério de pronto

- Volta completa de Le Mans continua fluida. **Feito e medido**, de 86 para 4 ms por movimento do cursor.
- Cor nunca é a única pista. **Feito e testado.** A comparação é tracejada em **todas** as linhas (antes, só na de pedais), e itálica no readout. No mapa, perder é linha cheia e mais grossa quanto mais rápido se perde, ganhar é tracejado, e no modo pedais o freio é grosso e a inércia tracejada. Um teste garante que nenhuma classe do mapa repete o par (espessura, traço). A legenda desenha cada linha como ela aparece.
- `AXIS_WIDTH` mantido para alinhar os gráficos. **Feito.**
- A faixa de legenda, chips e readout nunca define a largura mínima da janela: ela rola de lado quando estreita, como o cabeçalho.

## Riscos

Antialiasing continua desligado. O cache usa memória proporcional à área dos gráficos; o limite é teto, não alocação.

## Decisões (16/11/2026)

| Pergunta | Decisão |
| --- | --- |
| Quais canais aparecem por padrão? | **Velocidade, pedais e Δt**, como antes. Os outros estão a um clique nos chips. |
| Comparação tracejada em todas as linhas? | **Sim.** O custo do tracejado sumiu com o cache, e a cor deixa de ser a única pista. |
| Animar números no readout, como no NumberFlow? | **Não.** Telemetria se lê parada; animação atrasaria o número exato. A largura fixa resolve o "pulo" sem movimento. |

Testes: `tests/test_charts.py` (34): fundação, cache sem mudar nenhum pixel, tracejado em todas as linhas, readout, chips, mapa, pens cosméticos e as duas causas de lentidão.

---
titulo: Tabelas de curvas e consistência
resumo: A curva que mais custa marcada na tabela e no cartão pela mesma regra, colunas agrupadas sob uma faixa no cabeçalho, uma formatação só para todo número e chips no lugar dos combos da consistência.
ordem: 5
status: concluida
risco: medio
arquivos:
  - lmu_telemetry/presentation/corner_table.py
  - lmu_telemetry/presentation/corner_detail.py
  - lmu_telemetry/presentation/consistency_panel.py
  - lmu_telemetry/presentation/grouped_header.py
  - lmu_telemetry/presentation/chip_group.py
  - lmu_telemetry/presentation/theme.py
  - lmu_telemetry/application/pipeline.py
  - lmu_telemetry/shared/formatting.py
  - lmu_telemetry/shared/strings.py
  - tests/test_tables.py
  - tests/test_formatting.py
---

## Escopo

`CornerTable` mostra colunas condicionais (comparação e volta ideal) e permite renomear curvas. `ConsistencyPanel` mostra ranking por curva e gráfico volta a volta.

## Tarefas

1. ~~Hierarquia visual: destacar a curva que mais custa tempo~~ **Feito (16/11/2026).** Uma regra só, `pipeline.costliest_corner(rows)`, pura e sem Qt: com volta ideal, a curva com mais `gain_s`; sem ela e com comparação, a de maior `delta_s` positivo; sem nenhum dos dois, nenhuma. A tabela e o cartão da curva chamam a mesma função com as mesmas linhas, então não têm como discordar, e um teste percorre as curvas nos dois e compara. Na tabela, a linha inteira se destaca por três pistas: uma **barra âmbar** na borda esquerda, **todas as células em peso semibold** (`theme.emphasised`) e **"▸" antes do nome**. O número que decidiu (o "A ganhar") continua no tom `WARNING`, como antes. Se quem decidiu foi o Δt, ele mantém o vermelho de perda, que significa "mais lento". O cartão ganha uma linha "▸ A curva que mais custa · 0.262 s a ganhar contra a volta ideal", e a dica do nome na tabela diz o mesmo.
2. ~~Agrupar colunas de comparação e de volta ideal com cabeçalho claro~~ **Feito.** Um `QHeaderView` próprio (`grouped_header.GroupedHeader`) desenha uma faixa acima dos rótulos: **"Nesta volta"**, **"Contra a referência"** e **"Contra a volta ideal"**. A coluna do nome fica sem grupo, porque diz qual curva é e não mede nada. A faixa é calculada da geometria das seções a cada pintura, então acompanha rolagem lateral, redimensionamento e colunas ocultas sem nada para sincronizar. Um grupo todo oculto não desenha nada, e o rótulo é cortado (com reticências) na largura das suas colunas, nunca as alarga. A dica de cada coluna e a da faixa trazem o nome do grupo. As seções do cartão passaram a usar as mesmas palavras ("Volta ideal" virou "Contra a volta ideal").
3. ~~Padronizar formatação de tempo, diferença e velocidade em `formatting.py`~~ **Feito.** `format_seconds` (tempo sem sinal), `format_gap` (diferença com sinal), `format_speed` (de m/s para km/h, com `signed=` opcional) e `format_distance` (metros), ao lado de `format_lap_time`, `format_sector_time` e `format_value`. Todos devolvem só o número, sem unidade, e `"--"` (`MISSING`) para ausente, NaN ou infinito. Os helpers privados `_signed` e `_kmh` da tabela e do cartão e as f-strings soltas dos três painéis saíram. Os modelos em `strings.py` desses painéis perderam o especificador de formato (`{std:.3f}` virou `{std}`), e o número chega já formatado.
4. ~~Revisar o seletor de stint e de métrica do painel de consistência~~ **Feito.** Os dois combos viraram **chips** (`chip_group.ChipGroup`: `QToolButton` com `role="chip"` num `QButtonGroup` exclusivo, o mesmo visual dos canais do gráfico), numa linha de controles: stint à esquerda e medida à direita, acima do gráfico. Os chips de stint só aparecem com mais de um stint. A medida escolhida **se mantém** ao trocar de stint e ao abrir outra volta. Os chips trazem a unidade ("Frenagem (m)", "V mín (km/h)", "Acelerador (m)", com as mesmas palavras das colunas da tabela), e o nome completo fica no eixo, na dica e no nome acessível. O título do gráfico também ganhou a unidade ("média 2767.5 m · σ 77.1 m"). No teclado funciona como grupo de botões de rádio: Tab para só no chip escolhido e as setas mudam a escolha. Cada grupo tem nome acessível ("Stint", "Medida no gráfico volta a volta"), e cada chip de stint diz na dica quais voltas tem.

## Critério de pronto

- Linhas continuam na ordem da volta (sem ordenação). **Feito e testado.** O destaque marca a linha, não a move, e `setSortingEnabled(False)` continua lá.
- Nome de curva editável persiste no catálogo. **Feito e testado.** O "▸" é desenhado pelo delegate da coluna e não está no texto. Por isso não entra no editor e, de lá, no catálogo.
- Corte de aviso vindo da configuração (`ui.consistency.*`). **Mantido.**
- Nada aumenta a largura mínima da janela. **Medido, e ela diminuiu:** de **1261 × 669** para **757 × 682** px com a sessão demo. Antes, a linha "resumo + combo" do painel de consistência não quebrava e obrigava o painel a ter 674 px; agora o resumo, os chips e a linha da volta ideal acima da tabela de curvas quebram linha. O preço é a altura mínima, que subiu **13 px**, porque o resumo da consistência ganhou uma linha própria. Ver "Ficou para depois".

## O que mudou na tela de propósito

| Antes | Agora | Por quê |
| --- | --- | --- |
| `-0.000` numa diferença que arredonda para zero (lista de voltas, cabeçalho, legenda, tabela, cartão) | `+0.000`; `-0.0` km/h vira `+0.0` | Sinal de menos num zero parece perda que não existe. |
| `nan` em ápice, trail, inércia ou σ quando faltava o dado | `--` | Mesma regra de todo o resto. |
| `-- km/h`, `-- m`, `em -- m` no cartão | `--` | "-- km/h" parece valor existente e desconhecido, e não há valor nenhum. |
| Cartão pintava de âmbar qualquer "A ganhar" acima de 0,05 s | Só o da curva que a tabela marca | O cartão marcava curvas que a tabela não marcava. |
| Seção "Volta ideal" no cartão | "Contra a volta ideal" | As mesmas palavras da faixa da tabela. |
| Título do gráfico de consistência sem unidade | Com unidade | Pedido da tarefa. |
| Coluna "Curva" da consistência esticada (e espremida para "T1…" com o painel estreito) | Largura do conteúdo, e a sobra vai para a última | A mesma decisão de 07/11 para a tabela de curvas. |
| Os docks de baixo com 669 / 241 / 674 px (curvas / cartão / consistência) a 1600 px | 792 / 285 / 507 px | A consistência deixou de impor 674 px, e os docks seguem as proporções de `_arrange_docks`. |

## Decisões (16/11/2026)

| Pergunta | Decisão |
| --- | --- |
| Onde mora a regra da "curva que mais custa"? | **`application/pipeline.py`, ao lado de `CornerRow`.** É lógica sobre as linhas, sem Qt, e os dois painéis já importam dali. Devolve a posição, os segundos e a base (`CostBasis.IDEAL` ou `COMPARISON`), para o texto dizer contra o quê. |
| Com volta ideal mas nada a ganhar, cair para a comparação? | **Não.** Se a volta ideal existe, ela decide. Cair para a comparação marcaria uma curva que a sessão já fez no seu melhor. Empate fica com a primeira curva da volta, e ganho ou empate nunca é "custo". |
| Tingir a linha inteira? | **Não; uma barra na borda.** O primeiro teste foi um tingimento âmbar a 12% (o do banner de aviso). O vermelho de perda passa o AA no painel por pouco (4,6:1) e caiu para 3,7:1 sobre o tingimento. A barra dá a pista de cor sem ficar atrás de texto, e um teste do tema guarda o motivo. |
| Faixa de grupo: alinhada à esquerda ou centralizada? | **Centralizada**, como os rótulos das colunas embaixo dela. |
| Chips de medida acima do gráfico ou na linha de controles? | **Na linha de controles, à direita, sobre o gráfico.** Acima do gráfico, os três chips quebravam em duas linhas num painel de ~200 px, e o gráfico ficava com ~50 px de altura no tamanho padrão. |
| Chips num `QScrollArea`, como os canais? | **Não; eles quebram linha** (`chip_group.FlowLayout`). Rolagem esconderia stints, e uma barra de rolagem custaria altura mesmo quando cabe tudo. |

Medido: `scripts/bench_charts.py` antes (worktree em `HEAD`) e depois deu load 86 / 86 ms, cursor 4,2 / 3,8 ms e pan 37 / 37 ms, sem diferença. Nenhum gráfico do bench foi tocado.

Testes: `tests/test_tables.py` (48): a regra parametrizada, a linha marcada (peso, barra em pixel, marca desenhada e fora do texto, renomear depois da marca, nome sem corte), o cartão concordando com a tabela, a faixa (grupos ocultos, rolagem, redimensionamento, nunca alarga coluna) e os seletores (stint oculto com um, medida mantida, stint curto que não prende o usuário, unidades, nomes acessíveis, setas, largura mínima). `tests/test_formatting.py` (127): cada helper com `None`, NaN, ±inf, zero, negativos e valor que arredonda para zero. Mais dois em `tests/test_theme.py` (a barra e o porquê dela) e um ajuste em `tests/test_ui.py`, onde trocar de medida agora é clicar no chip.

## Defeito encontrado no caminho

Trocar para um stint curto demais para medir chamava `clear()`, que escondia **também** os seletores de stint. Não havia como voltar aos outros stints sem abrir outra volta. Agora um stint sem medida mostra o aviso e mantém os chips de stint.

## Ficou para depois

- **Altura mínima +13 px** (669 → 682), pela linha própria do resumo da consistência. A janela ainda cabe numa tela de 768 px. Dá para recuperar quando o resumo puder dividir a linha com os controles, o que pede outro arranjo da linha de baixo (etapa 6).
- **A faixa de grupo custa 16 px** no cabeçalho da tabela de curvas (36 → 52 px), cerca de meia linha. No layout padrão a 1000 px de altura a linha de baixo tem 178 px, e já era apertada antes.
- O cartão diz "Sem comparação ativa" no modo "Volta ideal", porque a volta ideal não conta como volta de comparação (`has_benchmark_lap`). Isso não mudou aqui.
- O ranking da consistência continua com o seu próprio destaque (a primeira linha em âmbar). Ele responde outra pergunta, repetibilidade e não tempo da volta, e não usa `costliest_corner`.

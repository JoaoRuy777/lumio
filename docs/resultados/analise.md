## Análise

**Latência de alarme.** Nenhuma das 120 quedas provocadas (40 por nível)
ficou sem alarme. A mediana ficou entre 9 e 12 ms em todos os níveis, e o
p99 subiu de 23 para 55 ms com 3.200 ONUs. Do coletor ao banco (Redis,
regras e gravação), o tempo ficou em ~5–6 ms. O resto é o simulador gerando a
trap e o coletor recebendo, o que mostra que o caminho da trap não é
gargalo. Na tela, o alarme aparece depois de mais ~0,1 s (SSE pelo nginx,
medido na sprint 4); o teste de ponta a ponta exige no máximo 5 s.

**Vazão do worker.** O primeiro teste mostrou que o worker fazia uma
consulta ao banco **por ONU** (1.473 ONUs/s). Depois da mudança para
gravação em lote, o mesmo teste deu **35.645 ONUs/s** (24× mais). Nos níveis
seguintes, a rajada ficou entre 7.500 e 12.300 ONUs/s. A variação não segue
o tamanho da rede (10 OLTs deu menos que 25), então é ruído de medição: cada
rajada dura 1 a 4 s, roda uma vez só, junto da coleta real das OLTs e numa
máquina compartilhada com o Windows e outros programas. Mesmo o **pior
valor medido (7.528 ONUs/s) é ~140 vezes** a carga normal do maior nível (53
estados de ONU por segundo). Num ciclo de 60 s, isso daria para ~450 mil
ONUs só pelo worker, bem acima de qualquer provedor regional.

**Coleta SNMP.** A coleta de uma OLT (128 ONUs) passou de 0,3 s para 2,6 s
com 25 OLTs. A causa provável é o **simulador**: um processo Python só
responde por todas as OLTs, então as coletas simultâneas fazem fila nele.
OLTs reais respondem cada uma por si. Mesmo assim, 2,6 s é bem menos que o
intervalo de 60 s entre coletas.

**CPU e memória.** Com 3.200 ONUs, a Lumio inteira usou em média **~24 % de
um núcleo e ~290 MiB de RAM**. Uma VPS de 2 vCPU e 4 GB (a sugerida em
`docs/deploy.md`) tem folga grande para o MVP.

**Limitações.**
- Um teste por nível, numa máquina só (o simulador disputa a CPU com a
  Lumio). Os números servem de ordem de grandeza, não de limite exato.
- O nível de 50 OLTs (6.400 ONUs) não foi medido: a máquina de teste ficou
  sem memória livre. Ele fica no script (`LEVELS="2 10 25 50"`, o padrão).
- O "antes" só tem o nível de 2 OLTs, medido antes da otimização.
- A latência não inclui o atraso de rede até OLTs reais, nem a detecção só
  por polling (sem trap), que depende do ciclo de 60 s.

---
layout: default
title: Qualidade de Dados no BrCris
---

# Qualidade de Dados no BrCris

Relatórios da avaliação da qualidade de dados da camada gold do BrCris, feita como parte do Trabalho de Conclusão de Curso (UFRJ). Foram aplicadas 230 regras de validação a 10 classes de dados, organizadas por dimensão de qualidade: completude, unicidade, validade e consistência.

## Relatório geral

- [Relatório final](reports/relatorio_final_brcris.html): panorama, resultados por classe e análise dos padrões de falha
- [Validações por classe](validacoes_por_classe.html): lista de todas as regras aplicadas em cada classe
- [README](README.html): como o pipeline funciona e como reproduzi-lo

## Relatórios de qualidade por classe

Score por entidade e por dimensão, resultado de cada regra e até 5 exemplos de falha.

| Classe | Relatório de qualidade | Exploração dos dados |
|---|---|---|
| Publicação | [abrir](reports/publication/report.html) | [abrir](reports/exploration/publication.html) |
| Pessoa | [abrir](reports/person/report.html) | [abrir](reports/exploration/person.html) |
| Periódico | [abrir](reports/journal/report.html) | [abrir](reports/exploration/journal.html) |
| Patente | [abrir](reports/patent/report.html) | [abrir](reports/exploration/patent.html) |
| Grupo de pesquisa | [abrir](reports/researchgroup/report.html) | [abrir](reports/exploration/researchgroup.html) |
| Software | [abrir](reports/software/report.html) | [abrir](reports/exploration/software.html) |
| Curso | [abrir](reports/course/report.html) | — |
| Programa | [abrir](reports/program/report.html) | [abrir](reports/exploration/program.html) |
| Unidade organizacional | [abrir](reports/orgunit/report.html) | [abrir](reports/exploration/orgunit.html) |
| Relações | [abrir](reports/relations/report.html) | — |

## Código

O código do pipeline está neste repositório: [github.com/nicxlw/data_quality_brcris](https://github.com/nicxlw/data_quality_brcris).

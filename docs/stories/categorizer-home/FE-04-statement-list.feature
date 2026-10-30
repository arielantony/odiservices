@FE-04 @prototype-v3 @draft
Feature: List sent statements
  As a member of the finance team
  I want to see every statement I sent and its status
  So that I know which ones are ready, still processing or failed

  Prototype: docs/prototypes/portal/v3.html#home
  Not covered yet (needs prototype): no statements sent yet, list failed to load.

  Background:
    Given these fictitious statements exist:
      | name                             | sent at          | status      | pending review | total        |
      | Fatura Cartão Exemplo, set/2026  | 02/10/2026 14:12 | ready       | 2              | R$ 11.906,35 |
      | Fatura Cartão Exemplo, ago/2026  | 03/09/2026 09:40 | ready       | 0              | R$ 9.412,80  |
      | Fatura Cartão Demo, jul/2026     | 04/08/2026 18:05 | classifying | 0              |              |
      | Fatura Teste, jun/2026           | 05/07/2026 11:22 | failed      | 0              |              |
    And I am on the "Categorizer home" screen

  Scenario: Statements are listed newest first
    Then "Faturas enviadas" lists, in this order:
      | Fatura Cartão Exemplo, set/2026 |
      | Fatura Cartão Exemplo, ago/2026 |
      | Fatura Cartão Demo, jul/2026    |
      | Fatura Teste, jun/2026          |
    And I see the note "Mais recentes primeiro"

  Scenario Outline: Each statement shows its status and total
    Then the row "<name>" shows the date "<sent at>"
    And the row "<name>" shows the status "<status label>"
    And the row "<name>" shows "<value>" in the total column

    Examples:
      | name                            | sent at          | status label           | value          |
      | Fatura Cartão Exemplo, set/2026 | 02/10/2026 14:12 | 2 para revisar         | R$ 11.906,35   |
      | Fatura Cartão Exemplo, ago/2026 | 03/09/2026 09:40 | Concluída              | R$ 9.412,80    |
      | Fatura Cartão Demo, jul/2026    | 04/08/2026 18:05 | Classificando          | —              |
      | Fatura Teste, jun/2026          | 05/07/2026 11:22 | Falhou: PDF ilegível   | Tentar de novo |

  Scenario: Opening a ready statement
    When I open "Fatura Cartão Exemplo, set/2026"
    Then I am on the "Categorizer board" screen for "Fatura Cartão Exemplo, set/2026"

  Scenario: Loading older statements
    Given more statements exist than fit on the first page
    When I select "Mostrar faturas anteriores"
    Then older statements are added to the end of the list

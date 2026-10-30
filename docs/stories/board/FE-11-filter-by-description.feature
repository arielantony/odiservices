@FE-11 @prototype-v3 @draft
Feature: Filter cards by description
  As a member of the finance team
  I want to filter the board by description
  So that I can find a specific transaction quickly

  Prototype: docs/prototypes/portal/v3.html#board
  Not covered yet (needs prototype): no card matches the filter.
  Open question: whether lane counts and totals follow the filter.

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: The slash key focuses the filter
    When I press "/"
    Then the field "Filtrar por descrição" has focus

  Scenario: Only matching cards stay visible
    When I type "Exemplo" in "Filtrar por descrição"
    Then only these cards are visible:
      | Distribuidora Exemplo Ltda |
      | Anúncios Online Exemplo    |
      | Contabilidade Exemplo      |
      | Tarifa Bancária Exemplo    |
      | Estorno Loja Exemplo       |

  Scenario: Clearing the filter shows every card again
    Given I typed "Exemplo" in "Filtrar por descrição"
    When I clear "Filtrar por descrição"
    Then all 17 cards are visible

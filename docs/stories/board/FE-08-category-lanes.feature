@FE-08 @prototype-v3 @draft
Feature: Category lanes and transaction cards
  As a member of the finance team
  I want each transaction shown as a card in its category lane
  So that I can check the classification at a glance

  Prototype: docs/prototypes/portal/v3.html#board

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: There is one lane per accounting category, in a fixed order
    Then I see these lanes, in this order:
      | Fornecedor             |
      | Operacional            |
      | Marketing/comercial    |
      | Investimento           |
      | Despesa administrativa |
      | Folha de pagamento     |
      | Custo do carro         |
      | Despesas financeiras   |
      | Pessoa física          |
      | Outros                 |

  Scenario Outline: Each lane shows its count and total
    Then the lane "<lane>" shows the count "<count>" and the total "<total>"

    Examples:
      | lane        | count | total       |
      | Fornecedor  | 3     | R$ 1.772,00 |
      | Operacional | 2     | R$ 548,00   |
      | Outros      | 2     | −R$ 42,30   |

  Scenario: Lanes with doubtful cards show how many are pending
    Then the lane "Operacional" shows "1 para revisar"
    And the lane "Outros" shows "1 para revisar"
    And the lane "Fornecedor" does not show "para revisar"

  Scenario: An empty lane invites a drop
    Then the lane "Pessoa física" shows "Nenhum lançamento aqui. Arraste um cartão para esta categoria."

  Scenario: A card shows description, value and date
    Then the card "Distribuidora Exemplo Ltda" shows "R$ 1.250,00" and "05 set"

  Scenario: Credits are shown as negative values
    Then the card "Estorno Loja Exemplo" shows "−R$ 120,00"

  Scenario: A doubtful card stands out and offers actions
    Then the card "Software Gestão Teste" is highlighted as pending review
    And the card "Software Gestão Teste" offers "Confirmar" and "Mover"

  Scenario: A card I recategorized says so
    Then the card "Papelaria Fictícia" shows "Movido por você"

@FE-07 @prototype-v3 @draft
Feature: Spending distribution by category
  As a member of the finance team
  I want to see how the statement total splits across categories
  So that I can spot where most of the money went

  Prototype: docs/prototypes/portal/v3.html#board

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: The bar shows only categories with spending
    Then the distribution bar has one segment per category with a positive total
    And each segment's width is proportional to its category total
    And there is no segment for "Pessoa física" or "Outros"

  Scenario: The legend lists the three largest categories
    Then the legend lists, in this order:
      | category           | share |
      | Investimento       | 41%   |
      | Folha de pagamento | 25%   |
      | Fornecedor         | 15%   |
    And the legend ends with "e mais 5 categorias"

  Scenario: The distribution follows category changes
    When I move "Notebook Loja Fictícia" from "Investimento" to "Fornecedor"
    Then the legend lists "Fornecedor" first

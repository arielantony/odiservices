@FE-13 @prototype-v3 @draft
Feature: Export the statement as JSON
  As a member of the finance team
  I want to download the classified statement
  So that I can use it in the accounting tools

  Prototype: docs/prototypes/portal/v3.html#board

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: Exporting downloads the current classification
    Given I dragged "Correios Demo" from "Despesa administrativa" to "Operacional"
    When I select "Exportar JSON"
    Then a JSON file is downloaded
    And it contains the 17 transactions of "Fatura Cartão Exemplo, set/2026"
    And "Correios Demo" has the category "Operacional" in the file

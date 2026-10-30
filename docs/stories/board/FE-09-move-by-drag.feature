@FE-09 @prototype-v3 @draft
Feature: Move a transaction to another category by dragging
  As a member of the finance team
  I want to drag a card to another lane
  So that I can fix a wrong classification

  Prototype: docs/prototypes/portal/v3.html#board
  Not covered yet (needs prototype): drop target highlight while dragging,
  save failure.

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: Dragging a card to another lane recategorizes it
    When I drag "Correios Demo" from "Despesa administrativa" to "Operacional"
    Then the card "Correios Demo" is in the lane "Operacional"
    And the card "Correios Demo" shows "Movido por você"
    And the lane "Operacional" shows the count "3" and the total "R$ 580,40"
    And the lane "Despesa administrativa" shows the count "1" and the total "R$ 650,00"

  Scenario: The new category is saved
    Given I dragged "Correios Demo" from "Despesa administrativa" to "Operacional"
    When I reload the page
    Then the card "Correios Demo" is in the lane "Operacional"

  Scenario: Dropping a card back on its own lane changes nothing
    When I drag "Correios Demo" and drop it on "Despesa administrativa"
    Then the card "Correios Demo" does not show "Movido por você"

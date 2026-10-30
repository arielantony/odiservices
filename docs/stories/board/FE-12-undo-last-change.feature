@FE-12 @prototype-v3 @draft
Feature: Undo the last change
  As a member of the finance team
  I want to undo my last change on the board
  So that a mistaken move or confirmation is easy to revert

  Prototype: docs/prototypes/portal/v3.html#board
  Not covered yet (needs prototype): "Desfazer" when there is nothing to undo.

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: Undoing a move returns the card to its lane
    Given I dragged "Correios Demo" from "Despesa administrativa" to "Operacional"
    When I select "Desfazer"
    Then the card "Correios Demo" is in the lane "Despesa administrativa"
    And the card "Correios Demo" does not show "Movido por você"

  Scenario: Undoing a confirmation brings the doubt back
    Given I confirmed the card "Software Gestão Teste"
    When I select "Desfazer"
    Then the card "Software Gestão Teste" is highlighted as pending review
    And the ticket shows "Para revisar" as "2"

  Scenario: Undo is saved
    Given I dragged "Correios Demo" from "Despesa administrativa" to "Operacional"
    And I selected "Desfazer"
    When I reload the page
    Then the card "Correios Demo" is in the lane "Despesa administrativa"

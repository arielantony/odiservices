@FE-10 @prototype-v3 @draft
Feature: Confirm a doubtful transaction
  As a member of the finance team
  I want to confirm a classification the system was unsure about
  So that only real doubts remain to be reviewed

  Prototype: docs/prototypes/portal/v3.html#board

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: Confirming keeps the category and clears the doubt
    When I select "Confirmar" on the card "Software Gestão Teste"
    Then the card "Software Gestão Teste" is still in the lane "Operacional"
    And the card "Software Gestão Teste" is no longer highlighted as pending review
    And the lane "Operacional" no longer shows "para revisar"
    And the ticket shows "Para revisar" as "1"

  Scenario: The confirmation is saved
    Given I confirmed the card "Software Gestão Teste"
    When I reload the page
    Then the card "Software Gestão Teste" is not highlighted as pending review

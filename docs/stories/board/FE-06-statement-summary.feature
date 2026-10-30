@FE-06 @prototype-v3 @draft
Feature: Statement summary on the board
  As a member of the finance team
  I want the board to open with the key numbers of the statement
  So that I know its size and how much review is left

  Prototype: docs/prototypes/portal/v3.html#board
  Not covered yet (needs prototype): the review button with 1 or 0 doubts.

  Background:
    Given the fictitious statement "Fatura Cartão Exemplo, set/2026"
    And I open it on the "Categorizer board" screen

  Scenario: The breadcrumb shows where the statement comes from
    Then the breadcrumb shows "Faturas enviadas" followed by "Fatura Cartão Exemplo, set/2026"

  Scenario: Returning to the list from the breadcrumb
    When I select "Faturas enviadas" in the breadcrumb
    Then I am on the "Categorizer home" screen

  Scenario: The ticket shows period, card and totals
    Then the ticket shows "Período" as "Set/2026"
    And the ticket shows "Cartão Exemplo final 0000"
    And the ticket shows "Total da fatura" as "R$ 11.906,35"
    And the ticket shows "Lançamentos" as "17"
    And the ticket shows "Para revisar" as "2"
    And I see the button "Revisar 2 dúvidas"

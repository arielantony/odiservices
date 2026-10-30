@FE-02 @prototype-v3 @draft
Feature: Categorizer service card on the landing page
  As a member of the finance team
  I want the landing page to summarize the state of the categorizer
  So that I can see what needs my attention before opening it

  Prototype: docs/prototypes/portal/v3.html#landing

  Background:
    Given these fictitious statements exist:
      | name                             | period   | status        | pending review |
      | Fatura Cartão Exemplo, set/2026  | set/2026 | ready         | 2              |
      | Fatura Cartão Exemplo, ago/2026  | ago/2026 | ready         | 0              |
      | Fatura Cartão Demo, jul/2026     | jul/2026 | classifying   | 0              |
      | Fatura Teste, jun/2026           | jun/2026 | failed        | 0              |
    And I open the landing page

  Scenario: The page header introduces the internal services
    Then I see the title "Serviços internos"
    And I see the text "Ferramentas da equipe Odisseia Viagens. Cada serviço guarda seu próprio histórico."

  Scenario: The service card summarizes the categorizer
    Then I see a service card titled "Categorizador" with the subtitle "Faturas de cartão"
    And the card shows "Última fatura" as "Set/2026"
    And the card shows "Para revisar" as "2 lançamentos"
    And the card shows "Faturas enviadas" as "4"

  Scenario: Opening the categorizer from the card
    When I select "Abrir categorizador"
    Then I am on the "Categorizer home" screen

  Scenario: Starting a new upload from the card
    When I select "Enviar nova fatura"
    Then I am on the "Categorizer home" screen
    And the upload area is ready to receive a file

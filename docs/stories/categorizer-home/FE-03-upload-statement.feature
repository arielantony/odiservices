@FE-03 @prototype-v3 @draft
Feature: Upload a card statement
  As a member of the finance team
  I want to send a card statement PDF
  So that its transactions are classified automatically

  Prototype: docs/prototypes/portal/v3.html#home
  Not covered yet (needs prototype): rejected file type, file over 10 MB,
  upload in progress, upload failure, name of the new row before
  classification finishes.

  Background:
    Given I am on the "Categorizer home" screen

  Scenario: The upload area explains what to send
    Then I see the title "Categorizador"
    And I see the text "Envie uma fatura de cartão em PDF. A classificação leva cerca de um minuto."
    And the upload area shows "Enviar fatura"
    And the upload area shows "Arraste o arquivo para cá ou escolha no computador. Até 10 MB."
    And the upload area shows "O PDF fica restrito à equipe financeira."

  Scenario: Choosing a PDF from the computer
    When I select "Escolher arquivo"
    And I choose the fictitious file "fatura-exemplo.pdf"
    Then a new row appears first in "Faturas enviadas" with the status "Classificando"

  Scenario: Dropping a PDF on the upload area
    When I drop the fictitious file "fatura-exemplo.pdf" on the upload area
    Then a new row appears first in "Faturas enviadas" with the status "Classificando"

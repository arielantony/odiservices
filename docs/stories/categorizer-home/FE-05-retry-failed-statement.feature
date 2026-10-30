@FE-05 @prototype-v3 @draft
Feature: Retry a failed statement
  As a member of the finance team
  I want to retry a statement whose classification failed
  So that I don't have to upload the same PDF again

  Prototype: docs/prototypes/portal/v3.html#home

  Background:
    Given the fictitious statement "Fatura Teste, jun/2026" failed with the reason "PDF ilegível"
    And I am on the "Categorizer home" screen

  Scenario: A failed statement explains why and offers a retry
    Then the row "Fatura Teste, jun/2026" shows the status "Falhou: PDF ilegível"
    And the row "Fatura Teste, jun/2026" shows the action "Tentar de novo"

  Scenario: Retrying puts the statement back into classification
    When I select "Tentar de novo" on the row "Fatura Teste, jun/2026"
    Then the row "Fatura Teste, jun/2026" shows the status "Classificando"
    And the row "Fatura Teste, jun/2026" no longer shows "Tentar de novo"

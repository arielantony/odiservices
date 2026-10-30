@FE-01 @prototype-v3 @ready
Feature: Top bar and navigation
  As a member of the finance team
  I want the same top bar on every portal screen
  So that I always know where I am and can move between services

  Prototype: docs/prototypes/portal/v3.html (all screens)

  Scenario: The top bar shows the brand and the navigation
    When I open any portal screen
    Then I see the Odisseia Viagens logo followed by "Serviços"
    And I see the navigation items "Início" and "Categorizador"
    And the top bar ends with an orange rule

  Scenario Outline: The current section is highlighted
    When I open the "<screen>" screen
    Then the navigation item "<item>" is highlighted
    And no other navigation item is highlighted

    Examples:
      | screen              | item          |
      | Landing             | Início        |
      | Categorizer home    | Categorizador |
      | Categorizer board   | Categorizador |

  Scenario Outline: Navigating from the top bar
    Given I am on the "<from>" screen
    When I select the navigation item "<item>"
    Then I am on the "<to>" screen

    Examples:
      | from              | item          | to               |
      | Landing           | Categorizador | Categorizer home |
      | Categorizer home  | Início        | Landing          |
      | Categorizer board | Categorizador | Categorizer home |

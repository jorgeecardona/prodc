Feature: Orders board

  @implemented
  Scenario: Past due orders are highlighted
    Given an order whose due date has passed
    When I open the orders board
    Then the order is highlighted as past due

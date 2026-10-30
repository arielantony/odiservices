import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "../../app/router";
import { TopBar } from "./TopBar";

function renderAt(path: string) {
  const router = createMemoryRouter(
    [{ path: "*", element: <TopBar /> }],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
}

describe("TopBar", () => {
  it("renders brand and navigation", () => {
    renderAt("/");
    expect(screen.getByRole("img", { name: "Odisseia Viagens" })).toBeInTheDocument();
    expect(screen.getByText("Serviços")).toBeInTheDocument();
    const links = within(screen.getByRole("navigation")).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Início", "Categorizador"]);
    expect(screen.getByText("Equipe financeira")).toBeInTheDocument();
  });

  it.each([
    ["/", "Início"],
    ["/categorizer", "Categorizador"],
    ["/categorizer/abc-123", "Categorizador"],
  ])("marks exactly one current item (%s)", (path, expected) => {
    renderAt(path);
    const current = screen
      .getAllByRole("link")
      .filter((l) => l.getAttribute("aria-current") === "page");
    expect(current.map((l) => l.textContent)).toEqual([expected]);
  });

  it("links point to the section routes", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: "Início" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Categorizador" })).toHaveAttribute(
      "href",
      "/categorizer",
    );
  });

  it("navigates without reload", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    render(<RouterProvider router={router} />);
    await userEvent.click(screen.getByRole("link", { name: "Categorizador" }));
    expect(router.state.location.pathname).toBe("/categorizer");
    expect(screen.getByRole("link", { name: "Categorizador" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("nav has an accessible name", () => {
    renderAt("/");
    expect(screen.getByRole("navigation", { name: "Navegação principal" })).toBeInTheDocument();
  });

  it("logo mark is decorative", () => {
    const { container } = render(
      <RouterProvider
        router={createMemoryRouter([{ path: "*", element: <TopBar /> }], { initialEntries: ["/"] })}
      />,
    );
    const mark = container.querySelector("img[alt='']");
    expect(mark).not.toBeNull();
    expect(screen.getAllByRole("img")).toHaveLength(1);
  });
});

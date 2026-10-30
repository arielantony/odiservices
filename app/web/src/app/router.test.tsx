import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { routes } from "./router";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
}

describe("router", () => {
  it.each(["/", "/categorizer", "/categorizer/abc-123"])(
    "renders each route inside the layout (%s)",
    (path) => {
      renderAt(path);
      expect(within(screen.getByRole("main")).getByText("Em migração")).toBeInTheDocument();
    },
  );

  it("unknown path renders not found", () => {
    renderAt("/nao-existe");
    expect(screen.getByText("Página não encontrada.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voltar ao início" })).toHaveAttribute("href", "/");
  });
});

import { createBrowserRouter, type RouteObject } from "react-router";
import { BoardPage } from "../features/categorizer/BoardPage";
import { CategorizerHomePage } from "../features/categorizer/CategorizerHomePage";
import { LandingPage } from "../features/landing/LandingPage";
import { Layout } from "./Layout";
import { NotFound } from "./NotFound";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/categorizer", element: <CategorizerHomePage /> },
      { path: "/categorizer/:statementId", element: <BoardPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);

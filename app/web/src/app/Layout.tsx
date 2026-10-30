import { Outlet } from "react-router";
import { TopBar } from "../components/TopBar/TopBar";

export function Layout() {
  return (
    <>
      <TopBar />
      <main>
        <Outlet />
      </main>
    </>
  );
}

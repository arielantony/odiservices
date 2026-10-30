import { Link } from "react-router";

export function NotFound() {
  return (
    <>
      <p>Página não encontrada.</p>
      <Link to="/">Voltar ao início</Link>
    </>
  );
}

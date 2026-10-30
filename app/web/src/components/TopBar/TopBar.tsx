import { Link, useLocation } from "react-router";
import mark from "../../assets/odisseia-mark.png";
import wordmark from "../../assets/odisseia-wordmark.png";
import styles from "./TopBar.module.css";

const items = [
  { label: "Início", to: "/", isCurrent: (path: string) => path === "/" },
  {
    label: "Categorizador",
    to: "/categorizer",
    isCurrent: (path: string) => path === "/categorizer" || path.startsWith("/categorizer/"),
  },
];

export function TopBar() {
  const { pathname } = useLocation();

  return (
    <header className={styles.topbar}>
      <span className={styles.logo}>
        <img src={mark} alt="" height={42} />
        <img src={wordmark} alt="Odisseia Viagens" height={30} />
        <span className={styles.svc}>Serviços</span>
      </span>
      <nav aria-label="Navegação principal" className={styles.nav}>
        {items.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            aria-current={item.isCurrent(pathname) ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <span className={styles.who}>Equipe financeira</span>
    </header>
  );
}

// src/components/BottomNav.tsx
import React from 'react';
import styles from '../styles/BottomNav.module.css';

// Для иконок можно использовать SVG или библиотеку иконок (например, react-icons)
// Пока используем текстовые заглушки или простые символы
const NavItem: React.FC<{ label: string; icon?: string; active?: boolean }> = ({ label, icon, active }) => {
  return (
    <button className={`${styles.navItem} ${active ? styles.active : ''}`}>
      {icon && <span className={styles.navIcon}>{icon}</span>}
      <span className={styles.navLabel}>{label}</span>
    </button>
  );
};

const BottomNav: React.FC = () => {
  // В будущем здесь будет логика для определения активной страницы
  const currentPage = 'Meet'; // Пример

  return (
    <nav className={styles.bottomNav}>
      <NavItem label="Meet" icon="💖" active={currentPage === 'Meet'} />
      <NavItem label="Messenger" icon="💬" active={currentPage === 'Messenger'} />
      <NavItem label="Communities" icon="👥" active={currentPage === 'Communities'} />
      <NavItem label="Profile" icon="👤" active={currentPage === 'Profile'} />
    </nav>
  );
};

export default BottomNav;
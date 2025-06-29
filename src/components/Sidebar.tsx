import React from 'react';
import '../styles/Sidebar.css'; // Создадим этот файл ниже

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  return (
    <>
      <div className={`sidebar-overlay ${isOpen ? 'open' : ''}`} onClick={onClose}></div>
      <div className={`sidebar ${isOpen ? 'open' : ''}`}>
        <nav>
          <ul>
            <li><a href="#main" onClick={onClose}>Main</a></li>
            <li><a href="#about" onClick={onClose}>About us</a></li>
            <li><a href="#faq" onClick={onClose}>FAQ</a></li>
          </ul>
        </nav>
      </div>
    </>
  );
};

export default Sidebar;
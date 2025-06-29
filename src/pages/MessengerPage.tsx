import React, { useState, useEffect } from 'react';
import ProfileCard from '../components/ProfileCard';
import BottomNav from '../components/BottomNav';
import styles from '../styles/MeetPage.module.css';

// Тип профиля (можно вынести в отдельный файл types.ts)
interface ProfileData {
  id: string;
  name: string;
  age: number;
  bio: string;
  imageUrl?: string;
}

// Имитация данных от бэкенда
const MOCK_PROFILES: ProfileData[] = [
  {
    id: '1',
    name: 'Elina',
    age: 28,
    bio: 'Love hiking, photography, and exploring new cafes. Looking for someone with a good sense of humor and adventurous spirit. 🌲📸☕️',
    imageUrl: 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8cG9ydHJhaXR8ZW58MHx8MHx8fDA%3D&auto=format&fit=crop&w=300&q=60' // Замени на реальные URL или оставь для placeholder
  },
  {
    id: '2',
    name: 'Marcus',
    age: 32,
    bio: 'Software developer by day, aspiring chef by night. Enjoy board games, sci-fi movies, and long walks with my dog. Let\'s connect if you share similar interests! 💻🍳🎲',
    // imageUrl: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8NHx8cG9ydHJhaXR8ZW58MHx8MHx8fDA%3D&auto=format&fit=crop&w=300&q=60'
  }, // У этого профиля будет placeholder
  {
    id: '3',
    name: 'Sophia',
    age: 25,
    bio: 'Passionate about art, music, and sustainable living. Always up for a deep conversation or a spontaneous road trip. ✨🎶🌍 Seeking a kind and open-minded partner.',
    imageUrl: 'https://images.unsplash.com/photo-1502823403499-6ccfcf4fb453?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Nnx8cG9ydHJhaXR8ZW58MHx8MHx8fDA%3D&auto=format&fit=crop&w=300&q=60'
  },
];

const MeetPage: React.FC = () => {
  const [profiles, setProfiles] = useState<ProfileData[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    // Имитация загрузки профилей
    // В реальном приложении здесь будет запрос к API
    setProfiles(MOCK_PROFILES);
  }, []);

  // Логика для смены профилей (пока не реализована в UI карточки)
  // const handleNextProfile = () => {
  //   setCurrentIndex((prevIndex) => (prevIndex + 1) % profiles.length);
  // };

  const currentProfile = profiles[currentIndex];

  return (
    <div className={styles.meetPageContainer}>
      <div className={styles.pageHeader}>
        {/* Можно добавить заголовок страницы или лого */}
        <h2>Discover New People</h2>
      </div>
      <main className={styles.profilesArea}>
        {profiles.length > 0 && currentProfile ? (
          <ProfileCard key={currentProfile.id} profile={currentProfile} />
        ) : (
          <p className={styles.loadingText}>Finding matches for you...</p>
        )}
        {/* Можно добавить кнопки для "следующий/предыдущий", если не свайпы */}
        {/* Или отображать несколько карточек сразу:
        {profiles.map(profile => (
          <ProfileCard key={profile.id} profile={profile} />
        ))}
        */}
      </main>
      <BottomNav />
    </div>
  );
};

export default MeetPage;
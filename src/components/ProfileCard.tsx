import React from 'react';
import styles from '../styles/ProfileCard.module.css';
import placeholderImage from '../assets/placeholder-profile.png'; // Путь к твоему плейсхолдеру

interface Profile {
  id: string;
  name: string;
  age: number;
  bio: string;
  imageUrl?: string;
}

interface ProfileCardProps {
  profile: Profile;
}

const ProfileCard: React.FC<ProfileCardProps> = ({ profile }) => {
  return (
    <div className={styles.profileCard}>
      <div className={styles.imageContainer}>
        <img
          src={profile.imageUrl || placeholderImage}
          alt={profile.name}
          className={styles.profileImage}
        />
      </div>
      <div className={styles.profileInfo}>
        <h3 className={styles.profileName}>{profile.name}, {profile.age}</h3>
        <p className={styles.profileBio}>{profile.bio}</p>
        {/* Можно добавить теги или интересы */}
        {/* <div className={styles.profileTags}>
          <span>Music</span>
          <span>Art</span>
          <span>Travel</span>
        </div> */}
      </div>
      <div className={styles.actions}>
        <button className={`${styles.actionButton} ${styles.passButton}`}>✕</button>
        <button className={`${styles.actionButton} ${styles.likeButton}`}>❤</button>
      </div>
    </div>
  );
};

export default ProfileCard;
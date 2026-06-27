import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Overview from "./pages/Overview.jsx";
import CreateVideo from "./pages/CreateVideo.jsx";
import GenerateAudio from "./pages/GenerateAudio.jsx";
import AudioLibrary from "./pages/AudioLibrary.jsx";
import BuildFromAudio from "./pages/BuildFromAudio.jsx";
import VideoHistory from "./pages/VideoHistory.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="create" element={<CreateVideo />} />
        <Route path="tts" element={<GenerateAudio />} />
        <Route path="audios" element={<AudioLibrary />} />
        <Route path="build" element={<BuildFromAudio />} />
        <Route path="history" element={<VideoHistory />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
  try {
    const dataDir = path.join(process.cwd(), 'data', 'rotation');
    if (!fs.existsSync(dataDir)) {
      return NextResponse.json([]);
    }
    const files = fs.readdirSync(dataDir).filter((f) => f.endsWith('.json'));
    const reports = files.map((f) => {
      const raw = fs.readFileSync(path.join(dataDir, f), 'utf-8');
      return JSON.parse(raw);
    });
    return NextResponse.json(reports);
  } catch (e) {
    console.error('Error reading rotation data:', e);
    return NextResponse.json({ error: 'Failed to load rotation data' }, { status: 500 });
  }
}

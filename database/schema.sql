-- Create custom types for lot type and status
CREATE TYPE lot_type AS ENUM ('lottery', 'auction');
CREATE TYPE lot_status AS ENUM ('pending_deposit', 'active', 'finished_sold', 'finished_unsold', 'cancelled');

-- Table to store user information
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    full_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table to store information about lots (auctions/lotteries)
CREATE TABLE IF NOT EXISTS lots (
    lot_id SERIAL PRIMARY KEY,
    seller_id BIGINT NOT NULL REFERENCES users(user_id),
    lot_type lot_type NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    media_file_id VARCHAR(255), -- Telegram file ID
    media_type VARCHAR(50), -- 'photo', 'video'
    channel_post_id BIGINT,
    status lot_status NOT NULL DEFAULT 'pending_deposit',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP WITH TIME ZONE,
    winner_id BIGINT REFERENCES users(user_id),

    -- Auction specific fields
    start_price BIGINT,
    current_price BIGINT,
    min_step BIGINT,

    -- Lottery specific fields
    ticket_price BIGINT
);

-- Table to store bids for auctions
CREATE TABLE IF NOT EXISTS bids (
    bid_id SERIAL PRIMARY KEY,
    lot_id INT NOT NULL REFERENCES lots(lot_id) ON DELETE CASCADE,
    bidder_id BIGINT NOT NULL REFERENCES users(user_id),
    amount BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table to store tickets for lotteries
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id SERIAL PRIMARY KEY,
    lot_id INT NOT NULL REFERENCES lots(lot_id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(user_id)
);

-- Create indexes for better performance on frequently queried columns
CREATE INDEX IF NOT EXISTS idx_lots_status ON lots(status);
CREATE INDEX IF NOT EXISTS idx_lots_seller_id ON lots(seller_id);
CREATE INDEX IF NOT EXISTS idx_bids_lot_id ON bids(lot_id);
CREATE INDEX IF NOT EXISTS idx_tickets_lot_id ON tickets(lot_id);

-- Table to store generated escrow wallets for each lot
CREATE TABLE IF NOT EXISTS escrow_wallets (
    wallet_id SERIAL PRIMARY KEY,
    lot_id INT NOT NULL UNIQUE REFERENCES lots(lot_id) ON DELETE CASCADE,
    address VARCHAR(255) NOT NULL UNIQUE,
    public_key VARCHAR(255) NOT NULL,
    -- The private key will be encrypted before being stored
    encrypted_private_key TEXT NOT NULL,
    mnemonic_phrase TEXT, -- Mnemonic can also be encrypted
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table to store whitelisted NFT collection addresses
CREATE TABLE IF NOT EXISTS whitelisted_collections (
    collection_id SERIAL PRIMARY KEY,
    address VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

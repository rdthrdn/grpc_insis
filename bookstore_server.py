import grpc
from concurrent import futures
import uuid
import bookstore_pb2
import bookstore_pb2_grpc
from typing import Dict, List
import math
import time
import threading
from datetime import datetime
import queue

class BookStore:
    def __init__(self):
        self.books: Dict[str, bookstore_pb2.Book] = {}
        self.subscribers = []
        self.chat_messages = []
        self.active_chat_clients = {}  # username -> queue
    
    def add_book(self, book: bookstore_pb2.Book) -> None:
        self.books[book.id] = book
        # Notify subscribers
        for subscriber in self.subscribers:
            try:
                subscriber.put(book)
            except:
                self.subscribers.remove(subscriber)
    
    def get_book(self, book_id: str) -> bookstore_pb2.Book:
        return self.books.get(book_id)
    
    def search_books(self, query: str) -> List[bookstore_pb2.Book]:
        query = query.lower()
        return [
            book for book in self.books.values()
            if query in book.title.lower() or query in book.author.lower()
        ]
    
    def list_books(self, page: int, page_size: int) -> tuple[List[bookstore_pb2.Book], int, int]:
        books = list(self.books.values())
        total_books = len(books)
        total_pages = math.ceil(total_books / page_size)
        
        start = (page - 1) * page_size
        end = start + page_size
        return books[start:end], total_books, total_pages
    
    def add_subscriber(self, subscriber):
        self.subscribers.append(subscriber)
    
    def get_active_usernames(self):
        return list(self.active_chat_clients.keys())
    
    def add_chat_client(self, username, client_queue):
        self.active_chat_clients[username] = client_queue
        print(f"User {username} connected. Active users: {self.get_active_usernames()}")
    
    def remove_chat_client(self, username):
        if username in self.active_chat_clients:
            del self.active_chat_clients[username]
            print(f"User {username} disconnected. Active users: {self.get_active_usernames()}")
    
    def broadcast_chat_message(self, message, target_username=None):
        # Store message history, except for system messages
        if message.user != "SYSTEM":
            self.chat_messages.append(message)
        
        # If target is specified, send only to that user
        if target_username and target_username in self.active_chat_clients:
            try:
                self.active_chat_clients[target_username].put(message)
                # Also send to sender if it's not the same as target
                if message.user != target_username and message.user in self.active_chat_clients:
                    self.active_chat_clients[message.user].put(message)
            except Exception as e:
                print(f"Error sending to {target_username}: {str(e)}")
        else:
            # Send to all active clients (group chat)
            for username, client_queue in list(self.active_chat_clients.items()):
                try:
                    client_queue.put(message)
                except Exception as e:
                    print(f"Error broadcasting to {username}: {str(e)}")
                    self.remove_chat_client(username)

class BookStoreServicer(bookstore_pb2_grpc.BookStoreServicer):
    def __init__(self):
        self.store = BookStore()
    
    def AddBook(self, request, context):
        book_id = str(uuid.uuid4())
        book = bookstore_pb2.Book(
            id=book_id,
            title=request.title,
            author=request.author,
            isbn=request.isbn,
            stock=request.stock,
            price=request.price
        )
        self.store.add_book(book)
        return bookstore_pb2.AddBookResponse(
            book=book,
            success=True,
            message="Book added successfully"
        )
    
    def SearchBook(self, request, context):
        books = self.store.search_books(request.query)
        return bookstore_pb2.SearchBookResponse(books=books)
    
    def UpdateStock(self, request, context):
        book = self.store.get_book(request.book_id)
        if not book:
            return bookstore_pb2.UpdateStockResponse(
                success=False,
                message="Book not found"
            )
        
        book.stock = request.new_stock
        self.store.add_book(book)
        return bookstore_pb2.UpdateStockResponse(
            success=True,
            message="Stock updated successfully"
        )
    
    def ListBooks(self, request, context):
        books, total_books, total_pages = self.store.list_books(
            request.page,
            request.page_size
        )
        return bookstore_pb2.ListBooksResponse(
            books=books,
            total_books=total_books,
            total_pages=total_pages
        )
    
    def DeleteBook(self, request, context):
        if request.book_id not in self.store.books:
            return bookstore_pb2.DeleteBookResponse(
                success=False,
                message="Book not found"
            )
        
        del self.store.books[request.book_id]
        return bookstore_pb2.DeleteBookResponse(
            success=True,
            message="Book deleted successfully"
        )
    
    def SubscribeToNewBooks(self, request, context):
        import queue
        q = queue.Queue()
        self.store.add_subscriber(q)
        
        end_time = time.time() + request.duration_seconds
        while time.time() < end_time:
            try:
                book = q.get(timeout=1)
                yield book
            except queue.Empty:
                continue
    
    def BulkAddBooks(self, request_iterator, context):
        total_added = 0
        for request in request_iterator:
            book_id = str(uuid.uuid4())
            book = bookstore_pb2.Book(
                id=book_id,
                title=request.title,
                author=request.author,
                isbn=request.isbn,
                stock=request.stock,
                price=request.price
            )
            self.store.add_book(book)
            total_added += 1
        
        return bookstore_pb2.BulkAddResponse(
            total_books_added=total_added,
            success=True,
            message=f"Successfully added {total_added} books"
        )
    
    def Chat(self, request_iterator, context):
        # Extract first message to identify the client
        try:
            first_message = next(request_iterator)
            client_queue = queue.Queue()
            username = first_message.user
            
            # Handle special "GET_USERS" message
            if first_message.message == "GET_USERS":
                active_users = self.store.get_active_usernames()
                # Return list of active users
                for user in active_users:
                    if user != username:  # Don't include requesting user
                        yield bookstore_pb2.ChatMessage(
                            user=user,
                            message="ONLINE",
                            timestamp=int(time.time())
                        )
                return
            
            # Register this client for broadcasts
            self.store.add_chat_client(username, client_queue)
            
            # Process the message parameters for first message
            target = None
            if first_message.message != "LISTENING":
                if ":" in first_message.message:
                    parts = first_message.message.split(":", 1)
                    if len(parts) > 1 and parts[0].strip() in self.store.get_active_usernames():
                        target = parts[0].strip()
                        first_message.message = parts[1].strip()
                        
                # Broadcast a welcome message only for new chat clients, not listeners
                system_message = bookstore_pb2.ChatMessage(
                    user="SYSTEM",
                    message=f"{username} has joined the chat",
                    timestamp=int(time.time())
                )
                # Don't send join message to the user who is joining
                for user, q in self.store.active_chat_clients.items():
                    if user != username:
                        try:
                            q.put(system_message)
                        except:
                            pass
                            
                # If this is a real message (not just LISTENING), broadcast it
                if first_message.message != "LISTENING":
                    self.store.broadcast_chat_message(first_message, target)
            
            # Process the rest of the messages
            for request in request_iterator:
                # Check for private message format (username: message)
                target = None
                if ":" in request.message:
                    parts = request.message.split(":", 1)
                    if len(parts) > 1 and parts[0].strip() in self.store.get_active_usernames():
                        target = parts[0].strip()
                        request.message = parts[1].strip()
                
                # Broadcast the message to target or everyone
                self.store.broadcast_chat_message(request, target)
            
            # When client is disconnecting, notify others
            if username in self.store.active_chat_clients:
                system_message = bookstore_pb2.ChatMessage(
                    user="SYSTEM",
                    message=f"{username} has left the chat",
                    timestamp=int(time.time())
                )
                # Only send to other users, not to the one leaving
                for user, q in list(self.store.active_chat_clients.items()):
                    if user != username:
                        try:
                            q.put(system_message)
                        except:
                            pass
                            
            # Wait for messages to send back to this client
            while context.is_active():
                try:
                    # Get the next message to send to this client
                    message = client_queue.get(timeout=1)
                    yield message
                except queue.Empty:
                    continue
        except Exception as e:
            print(f"Chat error: {str(e)}")
        finally:
            # Clean up when client disconnects
            if 'username' in locals():
                self.store.remove_chat_client(username)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bookstore_pb2_grpc.add_BookStoreServicer_to_server(BookStoreServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("BookStore server started on port 50051")
    server.wait_for_termination()

if __name__ == '__main__':
    serve() 
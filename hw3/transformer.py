import torch
import torch.nn as nn
import math
import torch.nn.functional as F


def sliding_window_attention(q, k, v, window_size, padding_mask=None):
    '''
    Computes the simple sliding window attention from 'Longformer: The Long-Document Transformer'.
    This implementation is meant for multihead attention on batched tensors. It should work for both single and multi-head attention.
    :param q - the query vectors. #[Batch, SeqLen, Dims] or [Batch, num_heads, SeqLen, Dims]
    :param k - the key vectors.  #[Batch, *, SeqLen, Dims] or [Batch, num_heads, SeqLen, Dims]
    :param v - the value vectors.  #[Batch, *, SeqLen, Dims] or [Batch, num_heads, SeqLen, Dims]
    :param window_size - size of sliding window. Must be an even number.
    :param padding_mask - a mask that indicates padding with 0.  #[Batch, SeqLen]
    :return values - the output values. #[Batch, SeqLen, Dims] or [Batch, num_heads, SeqLen, Dims]
    :return attention - the attention weights. #[Batch, SeqLen, SeqLen] or [Batch, num_heads, SeqLen, SeqLen]
    '''
    assert window_size%2 == 0, "window size must be an even number"
    seq_len = q.shape[-2]
    embed_dim = q.shape[-1]
    batch_size = q.shape[0] 

    values, attention = None, None

    # TODO:
    #  Compute the sliding window attention.
    # NOTE: We will not test your implementation for efficiency, but you are required to follow these two rules:
    # 1) Implement the function without using for loops.
    # 2) DON'T compute all dot products and then remove the uneccessary comptutations 
    #    (both for tokens that aren't in the window, and for tokens that correspond to padding according to the 'padding mask').
    # Aside from these two rules, you are free to implement the function as you wish. 
    # ====== YOUR CODE: ======
    device = q.device
    no_heads_flag = False
    
    if len(q.size()) == 3:
        no_heads_flag = True
        q = q.unsqueeze(1) # Batch, num_heads, SeqLen, Dims
        k = k.unsqueeze(1) # Batch, num_heads, SeqLen, Dims
    
    num_heads = q.shape[1]
    
    if padding_mask is not None:
        padding_mask = padding_mask.bool()
        q = q.masked_fill(padding_mask.unsqueeze(1).unsqueeze(3).expand_as(q), 0)
        k = k.masked_fill(padding_mask.unsqueeze(1).unsqueeze(3).expand_as(k), 0)
        v = v.masked_fill(padding_mask.unsqueeze(1).unsqueeze(3).expand_as(v), 0)
    
    # merge batch_size and num_heads for calculation purposes
    q = q.reshape(batch_size * num_heads, seq_len, embed_dim) # Batch*num_heads, SeqLen, Dims
    k = k.reshape(batch_size * num_heads, seq_len, embed_dim).transpose(1, 2) # Batch*num_heads, Dims, SeqLen

    # Sliding window parameters
    stride = 1
    padding = window_size // 2

    # Add padding to k (to perform the sliding window on its columns)
    padded_tensor = torch.nn.functional.pad(k, (padding, padding))

    # Unfold the padded tensor with the specified window size and stride
    unfolded_tensor = padded_tensor.unfold(-1, window_size+1, stride)

    # Reshape the unfolded tensor to match the desired output shape
    new_tensor = unfolded_tensor.transpose(1, 2)

    # Calculate all the attention values (still not diagonal)
    attn_rows = torch.matmul(q.unsqueeze(2), new_tensor).squeeze(2)

    # Calculate the size of the new matrix
    rows, cols = seq_len, seq_len + (2 * padding)
    
    # Create an index tensor for selecting elements from the input matrix
    index_tensor = torch.arange(cols).unsqueeze(0) - torch.arange(rows).unsqueeze(1)

    # Mask out the elements outside the range of the input matrix
    diagonal_indices = (index_tensor >= 0) & (index_tensor < window_size + 1)
    diagonal_indices = diagonal_indices.repeat(batch_size*num_heads, 1).reshape(batch_size*num_heads, seq_len, -1)

    # Select elements from the input matrix using the index tensor and mask
    attention = torch.full(size=(batch_size * num_heads, rows, cols), fill_value=-9e15, device=device) # Batch*num_heads, SeqLen, SeqLen

    # Insert calculated rows into correct indices
    attention[diagonal_indices] = attn_rows.flatten()
    
    # Remove paddings created for the sliding window
    attention = attention[:, :, padding:-padding]
    
    attention /= math.sqrt(embed_dim)
    
    # split batch_size and num_heads
    attention = attention.reshape(batch_size, num_heads, seq_len, seq_len) # Batch, num_heads, SeqLen, SeqLen
    
    # remove num_heads dim if input didn't have it
    if no_heads_flag:
        attention = attention.squeeze(1)
    
    attention = F.softmax(attention, dim=-1)
    
    values = torch.matmul(attention, v)
    
    # ========================

    return values, attention



class MultiHeadAttention(nn.Module):
    
    def __init__(self, input_dim, embed_dim, num_heads, window_size):
        super().__init__()
        assert embed_dim % num_heads == 0, "Embedding dimension must be 0 modulo number of heads."
        
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.window_size = window_size
        
        # Stack all weight matrices 1...h together for efficiency
        # "bias=False" is optional, but for the projection we learned, there is no teoretical justification to use bias
        self.qkv_proj = nn.Linear(input_dim, 3*embed_dim)
        self.o_proj = nn.Linear(embed_dim, embed_dim)
        
        self._reset_parameters()

    def _reset_parameters(self):
        # Original Transformer initialization, see PyTorch documentation of the paper if you would like....
        nn.init.xavier_uniform_(self.qkv_proj.weight)
        self.qkv_proj.bias.data.fill_(0)
        nn.init.xavier_uniform_(self.o_proj.weight)
        self.o_proj.bias.data.fill_(0)

    def forward(self, x, padding_mask, return_attention=False):
        batch_size, seq_length, embed_dim = x.size()
        qkv = self.qkv_proj(x)
        
        # Separate Q, K, V from linear output
        qkv = qkv.reshape(batch_size, seq_length, self.num_heads, 3*self.head_dim)
        qkv = qkv.permute(0, 2, 1, 3) # [Batch, Head, SeqLen, 3*Dims]
        
        q, k, v = qkv.chunk(3, dim=-1) #[Batch, Head, SeqLen, Dims]
        
        # Determine value outputs
        # TODO:
        # call the sliding window attention function you implemented
        # ====== YOUR CODE: ======
        values, attention = sliding_window_attention(q, k, v, self.window_size, padding_mask)
        # ========================

        values = values.permute(0, 2, 1, 3) # [Batch, SeqLen, Head, Dims]
        values = values.reshape(batch_size, seq_length, embed_dim) #concatination of all heads
        o = self.o_proj(values)
        
        if return_attention:
            return o, attention
        else:
            return o
        
        
class PositionalEncoding(nn.Module):

    def __init__(self, d_model, max_len=5000): 
        """
        Inputs
            d_model - Hidden dimensionality of the input.
            max_len - Maximum length of a sequence to expect.
        """
        super().__init__()

        # Create matrix of [SeqLen, HiddenDim] representing the positional encoding for max_len inputs
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        
        # register_buffer => Tensor which is not a parameter, but should be part of the modules state.
        # Used for tensors that need to be on the same device as the module.
        # persistent=False tells PyTorch to not add the buffer to the state dict (e.g. when we save the model) 
        self.register_buffer('pe', pe, persistent=False)

    def forward(self, x):
        x = x + self.pe[:, :x.size(1)]
        return x
    
    

class PositionWiseFeedForward(nn.Module):
    def __init__(self, input_dim, hidden_dim):
        super(PositionWiseFeedForward, self).__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, input_dim)
        self.activation = nn.GELU()

    def forward(self, x):
        return self.fc2(self.activation(self.fc1(x)))

    
class EncoderLayer(nn.Module):
    def __init__(self, embed_dim, hidden_dim, num_heads, window_size, dropout=0.1):
        '''
        :param embed_dim: the dimensionality of the input and output
        :param hidden_dim: the dimensionality of the hidden layer in the feed-forward network
        :param num_heads: the number of heads in the multi-head attention
        :param window_size: the size of the sliding window
        :param dropout: the dropout probability
        '''
        super(EncoderLayer, self).__init__()
        self.self_attn = MultiHeadAttention(embed_dim, embed_dim, num_heads, window_size)
        self.feed_forward = PositionWiseFeedForward(embed_dim, hidden_dim)
        self.norm1 = nn.LayerNorm(embed_dim)
        self.norm2 = nn.LayerNorm(embed_dim)
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, x, padding_mask):
        '''
        :param x: the input to the layer of shape [Batch, SeqLen, Dims]
        :param padding_mask: the padding mask of shape [Batch, SeqLen]
        :return: the output of the layer of shape [Batch, SeqLen, Dims]
        '''
        # TODO:
        #   To implement the encoder layer, do the following:
        #   1) Apply attention to the input x, and then apply dropout.
        #   2) Add a residual connection from the original input and normalize.
        #   3) Apply a feed-forward layer to the output of step 2, and then apply dropout again.
        #   4) Add a second residual connection and normalize again.
        # ====== YOUR CODE: ======
        
        attn_outputs = self.self_attn(x, padding_mask) # Apply attention to the input x
        attn_outputs = self.dropout(attn_outputs) # apply dropout
        
        residual1 = x + attn_outputs  # residual connection
        norm1_outputs = self.norm1(residual1) # normalize
                
        ff_outputs = self.feed_forward(norm1_outputs) # feed forward
        ff_outputs = self.dropout(ff_outputs) # apply dropout
        
        residual2 = norm1_outputs + ff_outputs # residual connection
        norm2_outputs = self.norm2(residual2) # normalize
        
        x = norm2_outputs
        
        # ========================
        
        return x
    
    
    
class Encoder(nn.Module):
    def __init__(self, vocab_size, embed_dim, num_heads, num_layers, hidden_dim, max_seq_length, window_size, dropout=0.1):
        '''
        :param vocab_size: the size of the vocabulary
        :param embed_dim: the dimensionality of the embeddings and the model
        :param num_heads: the number of heads in the multi-head attention
        :param num_layers: the number of layers in the encoder
        :param hidden_dim: the dimensionality of the hidden layer in the feed-forward network
        :param max_seq_length: the maximum length of a sequence
        :param window_size: the size of the sliding window
        :param dropout: the dropout probability

        '''
        super(Encoder, self).__init__()
        self.encoder_embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.positional_encoding = PositionalEncoding(embed_dim, max_seq_length)

        self.encoder_layers = nn.ModuleList([EncoderLayer(embed_dim, hidden_dim, num_heads, window_size, dropout) for _ in range(num_layers)])

        self.classification_mlp = nn.Sequential(
            nn.Linear(embed_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1, bias=False)
            )
        self.dropout = nn.Dropout(dropout)

    def forward(self, sentence, padding_mask):
        '''
        :param sententence #[Batch, max_seq_len]
        :param padding mask #[Batch, max_seq_len]
        :return: the logits  [Batch]
        '''
        output = None

        # TODO:
        #  Implement the forward pass of the encoder.
        #  1) Apply the embedding layer to the input.
        #  2) Apply positional encoding to the output of step 1.
        #  3) Apply a dropout layer to the output of the positional encoding.
        #  4) Apply the specified number of encoder layers.
        #  5) Apply the classification MLP to the output vector corresponding to the special token [CLS] 
        #     (always the first token) to receive the logits.
        # ====== YOUR CODE: ======
        
        #  1) Apply the embedding layer to the input.
        embedded_sentence = self.encoder_embedding(sentence)
        
        #  2) Apply positional encoding to the output of step 1.
        encoded_embedding = self.positional_encoding(embedded_sentence)
        
        #  3) Apply a dropout layer to the output of the positional encoding.
        encoded_embedding = self.dropout(encoded_embedding)
        
        #  4) Apply the specified number of encoder layers.
        layer_inputs = encoded_embedding
        for encoder_layer in self.encoder_layers:
            layer_inputs = encoder_layer(layer_inputs, padding_mask)
        layers_output = layer_inputs
        
        #  5) Apply the classification MLP to the output vector corresponding to the special token [CLS] 
        #     (always the first token) to receive the logits.
        output = self.classification_mlp(layers_output[:, 0]).flatten()
        
        # ========================
        
        return output
    
    def predict(self, sentence, padding_mask, return_logits=False):
        '''
        :param sententence #[Batch, max_seq_len]
        :param padding mask #[Batch, max_seq_len]
        :return: the binary predictions  [Batch]
        '''
        logits = self.forward(sentence, padding_mask)
        preds = torch.round(torch.sigmoid(logits))
        if return_logits:
            return preds, logits
        return preds

    
    